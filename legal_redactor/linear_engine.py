"""Linear, human-style candidate acceptance for legal document redaction.

The engine accepts ordered discoveries in source order. Once an entity is
confirmed, it expands that entity into deterministic full-text replacement
rules. The source text is kept unchanged during acceptance so generated masks
cannot interfere with later recognition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .candidate_resolution import is_noisy_org_capture, resolve_candidate_overlaps
from .filters import clean_organization_text as _clean_organization_text
from .entity_registry import FullDocumentEntityRegistry
from .config import RedactionProfile
from .filters import is_false_org as _is_false_org
from .counters import TypeCounters
from .filters import is_false_person as _is_false_person
from .filters import looks_like_false_location as _looks_like_false_location
from .lexicon import FACT_SECTION_BOUNDARY_RE, INSTITUTION_SUFFIXES, LEGAL_SUFFIXES
from .location_utils import (
    ADMIN_SUFFIXES,
    get_location_core,
    is_compound_admin_path,
    location_suffix,
    mask_admin_cascade_path,
)
from .llm import is_noise_entity_text, is_noise_project_text
from .models import Candidate, MappingEntry
from .org_masking import (
    CompanyMaskPlan,
    alias_mask_for_organization,
    build_company_mask_plan,
    derived_organization_alias_cores,
    explicit_organization_aliases,
    find_related_company_plan,
    full_organization_mask_for_plan,
    has_explicit_bare_brand_alias,
    is_short_company_surface,
    organization_mask_for_surface,
    looks_like_complete_bare_company_body,
    mask_institution,
    simple_legal_suffix,
)



@dataclass
class LinearRuleEngine:
    counters: TypeCounters
    profile: RedactionProfile
    get_location_prefix: Callable[[str], str]
    sample_blacklist: set[str] = field(default_factory=set)
    person_blacklist: set[str] = field(default_factory=set)
    mappings: list[MappingEntry] = field(default_factory=list)
    known_locations: dict[str, str] = field(default_factory=dict)
    known_people: set[str] = field(default_factory=set)
    known_organizations: set[str] = field(default_factory=set)
    seen_originals: set[str] = field(default_factory=set)
    source_text: str = ""
    _alias_cores_cache: dict[str, frozenset[str]] = field(default_factory=dict, repr=False)
    _organization_plans: dict[str, CompanyMaskPlan] = field(default_factory=dict, repr=False)
    _registry_constraints: FullDocumentEntityRegistry | None = field(default=None, repr=False)
    _entity_masks: dict[str, str] = field(default_factory=dict, repr=False)
    _entity_org_plans: dict[str, CompanyMaskPlan] = field(default_factory=dict, repr=False)

    def discover(
        self,
        text: str,
        candidates: Iterable[Candidate] = (),
        llm_analysis: dict | None = None,
        *,
        respect_fact_section_boundary: bool = True,
        registry_constraints: FullDocumentEntityRegistry | None = None,
    ) -> list[MappingEntry]:
        scan_text = text
        if respect_fact_section_boundary:
            boundary_match = FACT_SECTION_BOUNDARY_RE.search(text)
            if boundary_match:
                scan_text = text[: boundary_match.start()]

        self.source_text = scan_text
        self._registry_constraints = registry_constraints
        accepted_candidates = self._apply_llm_verdicts(list(candidates), scan_text, llm_analysis or {})
        accepted_candidates = resolve_candidate_overlaps(accepted_candidates)

        for candidate in sorted(
            accepted_candidates,
            key=lambda item: (item.start, -len(item.text), -item.confidence),
        ):
            if candidate.text in self.sample_blacklist:
                continue
            if candidate.type in {"location", "grassroots_org"}:
                self.accept_location(candidate)
            elif candidate.type == "person":
                self.accept_person(candidate)
            elif candidate.type == "organization":
                self.accept_organization(candidate)
            elif candidate.type == "project":
                self.accept_project(candidate)

        self._expand_discovered_aliases()
        return self.mappings


    @staticmethod
    def _apply_llm_verdicts(
        candidates: list[Candidate],
        text: str,
        analysis: dict,
    ) -> list[Candidate]:

        rejected = {
            value for value in analysis.get("reject", [])
            if isinstance(value, str)
        }
        calibrations = analysis.get("calibrate", {})
        if not isinstance(calibrations, dict):
            calibrations = {}

        reviewed: list[Candidate] = []
        for candidate in candidates:
            calibrated = calibrations.get(candidate.text)
            if isinstance(calibrated, str):
                calibrated = calibrated.strip()
                if len(calibrated) >= 2:
                    nearby_start = max(0, candidate.start - 80)
                    nearby_end = min(len(text), candidate.end + 80)
                    start = text.find(calibrated, nearby_start, nearby_end)
                    if start >= 0:
                        reviewed.append(
                            Candidate(
                                type=candidate.type,
                                text=calibrated,
                                start=start,
                                end=start + len(calibrated),
                                source="linear_llm_calibrated",
                                confidence=0.95,
                                risk_level=candidate.risk_level,
                                auto_redact=True,
                                role=candidate.role,
                                metadata=candidate.metadata,
                            )
                        )
                        continue
            if candidate.text in rejected or is_noise_entity_text(candidate.text):
                continue
            reviewed.append(candidate)
        return reviewed


    def accept_location(self, candidate: Candidate) -> None:
        if not self.profile.redact_locations:
            return
        value = candidate.text.strip()
        parts = candidate.metadata.get("parts") if isinstance(candidate.metadata, dict) else None
        is_rule_admin_candidate = (
            candidate.source == "china_admin_rules"
            and isinstance(parts, dict)
            and bool(parts)
        )
        if (
            not is_rule_admin_candidate
            and _looks_like_false_location(self.source_text, candidate.start, candidate.end, value)
        ):
            return
        if is_compound_admin_path(value) or len(parts or {}) >= 2:
            masked = mask_admin_cascade_path(value, self.get_location_prefix)
            if masked != value:
                self._add("location", value, masked, candidate)
                if value.endswith("省") and len(value) > 1:
                    core = value[:-1]
                    self.known_locations[value] = masked
                    self.known_locations[core] = masked
                    self._add("location", core, masked, candidate)
            return
        core = get_location_core(value)
        if len(core) < 2:
            return
        suffix = location_suffix(value)
        prefix = self.get_location_prefix(core)
        masked = f"{prefix}{suffix}"
        self.known_locations[value] = masked
        self.known_locations[core] = masked
        self._add("location", value, masked, candidate)
        if core != value:
            self._add("location", core, masked, candidate)

    def accept_person(self, candidate: Candidate) -> None:
        if not self.profile.redact_persons:
            return
        value = candidate.text.strip()
        if (
            value in self.known_people
            or value in self.person_blacklist
            or not re.fullmatch(r"[\u4e00-\u9fa5·]{2,6}", value)
            or _is_false_person(value)
            or any(word in value for word in ("当事", "应予", "应当", "予以"))
        ):
            return
        self.known_people.add(value)
        entity_id = self._candidate_entity_id(candidate)
        if entity_id and entity_id in self._entity_masks:
            self.known_people.add(value)
            self._add("person", value, self._entity_masks[entity_id], candidate)
            return
        masked = f"{value[0]}某{self.counters.next(f'person_{value[0]}')}"
        if entity_id:
            self._entity_masks[entity_id] = masked
        self._add("person", value, masked, candidate)

    def accept_organization(self, candidate: Candidate) -> None:
        if not self.profile.redact_organizations:
            return
        raw_value = candidate.text.strip(" ：:，,。；;\n\t")
        value = _clean_organization_text(raw_value)
        if not value and candidate.source.startswith(("linear_llm", "full_document_llm")):
            value = raw_value
        if not value or value in self.known_organizations:
            return
        entity_id = self._candidate_entity_id(candidate)
        if entity_id and entity_id in self._entity_masks:
            plan = self._entity_org_plans.get(entity_id)
            masked = organization_mask_for_surface(value, plan) if plan is not None else self._entity_masks[entity_id]
            self.known_organizations.add(value)
            if plan is not None:
                self._organization_plans[value] = plan
                self._alias_cores_cache[value] = derived_organization_alias_cores(value)
            self._add("organization", value, masked, candidate)
            return
        if not candidate.source.startswith(("linear_llm", "full_document_llm")) and (
            _is_false_org(value) or is_noisy_org_capture(value)
        ):
            return

        if any(suffix in value for suffix in INSTITUTION_SUFFIXES):
            masked = mask_institution(value, self.known_locations)
            if masked is None:
                return
            self.known_organizations.add(value)
            self._add("organization", value, masked, candidate)
            return

        legal_suffix = next((suffix for suffix in LEGAL_SUFFIXES if value.endswith(suffix)), "")
        if not legal_suffix:
            if candidate.source.startswith(("linear_llm", "full_document_llm")) and len(value) >= 2 and not _is_false_org(f"{value}公司"):
                suffix = "局" if value.endswith("局") else "机构"
                self._add("organization", value, f"{self.counters.next('group_prefix')}{suffix}", candidate)
            return

        body = value[: -len(legal_suffix)]
        if candidate.source.startswith("hanlp_ner") and body.endswith(ADMIN_SUFFIXES):
            return

        if (
            legal_suffix in {"公司", "集团"}
            and candidate.source in {"linear_full_org", "hanlp_ner", "heuristic_ner"}
            and not looks_like_complete_bare_company_body(body)
            and not self._known_organization_allows_short_alias(body)
        ):
            return

        if entity_id and entity_id in self._entity_org_plans:
            plan = self._entity_org_plans[entity_id]
            masked = organization_mask_for_surface(value, plan)
            self.known_organizations.add(value)
            self._organization_plans[value] = plan
            self._alias_cores_cache[value] = derived_organization_alias_cores(value)
            self._entity_masks[entity_id] = masked
            self._add("organization", value, masked, candidate)
            return
        related_plan = None
        if not entity_id:
            related_plan = find_related_company_plan(
                value,
                self._organization_plans,
                self._alias_cores_cache,
                source_text=self.source_text,
            )
        if related_plan is not None:
            location_updates: tuple[tuple[str, str], ...] = ()
            if is_short_company_surface(value, brand=related_plan.brand):
                masked = organization_mask_for_surface(value, related_plan)
            else:
                masked, location_updates = full_organization_mask_for_plan(
                    value,
                    related_plan,
                    self.known_locations,
                    self.get_location_prefix,
                )
            for province, location_mask in location_updates:
                self.known_locations[province] = location_mask
                self._add("location", province, location_mask, candidate)
            self.known_organizations.add(value)
            self._organization_plans[value] = CompanyMaskPlan(
                value=value,
                full_mask=masked,
                brand=related_plan.brand,
                brand_mask=related_plan.brand_mask,
                legal_suffix=related_plan.legal_suffix,
                location_updates=location_updates,
                aliases=related_plan.aliases,
            )
            self._alias_cores_cache[value] = derived_organization_alias_cores(value)
            if entity_id:
                self._entity_org_plans[entity_id] = self._organization_plans[value]
                self._entity_masks[entity_id] = masked
            self._add("organization", value, masked, candidate)
            return

        plan = build_company_mask_plan(
            value=value,
            source_text=self.source_text,
            known_locations=self.known_locations,
            get_location_prefix=self.get_location_prefix,
            get_brand_mask=lambda _brand: self.counters.next("group_prefix"),
        )
        if plan is None:
            return

        for province, location_mask in plan.location_updates:
            self.known_locations[province] = location_mask
            self._add("location", province, location_mask, candidate)

        self.known_organizations.add(value)
        self._alias_cores_cache[value] = derived_organization_alias_cores(value)
        self._organization_plans[value] = plan
        if entity_id:
            self._entity_org_plans[entity_id] = plan
            self._entity_masks[entity_id] = plan.full_mask
        self._add("organization", value, plan.full_mask, candidate)

        for alias in plan.aliases:
            self._add("organization", alias, alias_mask_for_organization(alias, plan), candidate)
            if self._is_bare_explicit_organization_alias(alias):
                suffixed_alias = f"{alias}{simple_legal_suffix(plan.legal_suffix)}"
                if suffixed_alias in self.source_text:
                    self._add(
                        "organization",
                        suffixed_alias,
                        alias_mask_for_organization(suffixed_alias, plan),
                        candidate,
                    )
        if has_explicit_bare_brand_alias(self.source_text, plan.brand):
            self._add("organization", plan.brand, plan.brand_mask, candidate)

        company_alias = f"{plan.brand}公司"
        if company_alias in self.source_text:
            self._add("organization", company_alias, f"{plan.brand_mask}公司", candidate)

    @staticmethod
    def _is_bare_explicit_organization_alias(alias: str) -> bool:
        if not alias or len(alias) < 2:
            return False
        return not any(alias.endswith(suffix) for suffix in LEGAL_SUFFIXES + INSTITUTION_SUFFIXES)

    def _known_organization_allows_short_alias(self, alias_core: str) -> bool:
        if not alias_core or len(alias_core) < 2:
            return False
        if has_explicit_bare_brand_alias(self.source_text, alias_core):
            return True
        for organization in self.known_organizations:
            cores = self._alias_cores_cache.get(organization)
            if cores is None:
                cores = derived_organization_alias_cores(organization)
                self._alias_cores_cache[organization] = cores
            if alias_core in cores:
                return True
        return False

    @staticmethod
    def _candidate_entity_id(candidate: Candidate) -> str | None:
        value = candidate.metadata.get("registry_entity_id") if isinstance(candidate.metadata, dict) else None
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _candidate_restore_original(candidate: Candidate) -> str | None:
        value = candidate.metadata.get("registry_primary_text") if isinstance(candidate.metadata, dict) else None
        return value if isinstance(value, str) and value else None

    def _entity_do_not_merge_ids(self, entity_id: str | None) -> tuple[str, ...]:
        if not entity_id or self._registry_constraints is None:
            return ()
        blocked: list[str] = []
        for pair in self._registry_constraints.do_not_merge:
            if pair.left_id == entity_id:
                blocked.append(pair.right_id)
            elif pair.right_id == entity_id:
                blocked.append(pair.left_id)
        return tuple(blocked)

    def _expand_discovered_aliases(self) -> None:
        for organization in list(self.known_organizations):
            plan = self._organization_plans.get(organization)
            if plan is None:
                continue
            for alias in explicit_organization_aliases(self.source_text, organization):
                if alias in self.seen_originals or alias in self.known_organizations:
                    continue
                start = self.source_text.find(alias)
                if start < 0:
                    continue
                self._add(
                    "organization",
                    alias,
                    alias_mask_for_organization(alias, plan),
                    Candidate(
                        type="organization",
                        text=alias,
                        start=start,
                        end=start + len(alias),
                        source="linear_alias_expand",
                        confidence=0.9,
                        risk_level="medium",
                        auto_redact=True,
                    ),
                )


    def accept_project(self, candidate: Candidate) -> None:
        if not self.profile.redact_projects:
            return

        value = candidate.text.strip(" ：:，,。；;\n\t")
        if (
            not value
            or value in self.seen_originals
            or value in self.sample_blacklist
            or value in {"项目", "工程", "小区", "楼盘"}
            or len(value) < 3
            or is_noise_project_text(value)
        ):
            return
        suffix = "地"
        for ending in ("小区", "项目", "工程", "花园", "华府", "澜庭", "蓝庭", "公寓", "广场", "大厦", "产业园"):
            if value.endswith(ending):
                suffix = ending
                break
        masked = f"{self.counters.next('project')}{suffix}"
        self._add("project", value, masked, candidate)

    def _add(
        self,
        entity_type: str,
        original: str,
        masked: str,
        candidate: Candidate,
    ) -> None:
        if (
            not original
            or original in self.seen_originals
            or original in self.sample_blacklist
            or original == masked
        ):
            return
        self.seen_originals.add(original)
        self.mappings.append(
            MappingEntry(
                type=entity_type,
                original=original,
                masked=masked,
                role=candidate.role,
                source=f"linear:{candidate.source}",
                confidence=candidate.confidence,
                restore_by_default=True,
                entity_id=self._candidate_entity_id(candidate),
                do_not_merge=self._entity_do_not_merge_ids(self._candidate_entity_id(candidate)),
                restore_original=self._candidate_restore_original(candidate),
            )
        )
