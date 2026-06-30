"""Linear, human-style rule discovery for legal document redaction.

The engine reads discoveries in source order. Once an entity is confirmed, it
expands that entity into deterministic full-text replacement rules. The source
text is kept unchanged during discovery so generated masks cannot interfere
with later recognition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .candidate_resolution import is_noisy_org_capture, resolve_candidate_overlaps
from .china_admin_rules import detect_china_admin_rule_candidates
from .config import RedactionProfile
from .counters import TypeCounters
from .detectors import (
    _clean_organization_text,
    _is_false_person,
    _is_false_org,
    _looks_like_false_location,
    detect_fallback_person_candidates,
    detect_party_candidates,
    detect_title_candidates,
)
from .lexicon import (
    BARE_COMPANY_ALIAS_RE,
    FACT_SECTION_BOUNDARY_RE,
    INDUSTRY_TERMS,
    INSTITUTION_SUFFIXES,
    LEGAL_SUFFIXES,
    ORG_FULL_RE,
)
from .location_utils import (
    ADMIN_SUFFIXES,
    get_location_core,
    is_compound_admin_path,
    location_suffix,
    mask_admin_cascade_path,
    strip_leading_locations,
)
from .models import Candidate, MappingEntry
from .org_masking import (
    CompanyMaskPlan,
    alias_mask_for_organization,
    build_company_mask_plan,
    derived_organization_alias_cores,
    explicit_organization_aliases,
    has_explicit_bare_brand_alias,
    looks_like_complete_bare_company_body,
    mask_institution,
)

# Backward-compatible re-exports for pipeline/tests.
_derived_organization_alias_cores = derived_organization_alias_cores
_has_explicit_bare_brand_alias = has_explicit_bare_brand_alias
_explicit_organization_aliases = explicit_organization_aliases


@dataclass
class LinearRuleEngine:
    counters: TypeCounters
    profile: RedactionProfile
    sample_blacklist: set[str]
    get_location_prefix: Callable[[str], str]
    mappings: list[MappingEntry] = field(default_factory=list)
    known_locations: dict[str, str] = field(default_factory=dict)
    known_people: set[str] = field(default_factory=set)
    known_organizations: set[str] = field(default_factory=set)
    seen_originals: set[str] = field(default_factory=set)
    source_text: str = ""
    use_semantic_rules: bool = True
    use_china_admin_rules: bool = True
    _alias_cores_cache: dict[str, frozenset[str]] = field(default_factory=dict, repr=False)
    _organization_plans: dict[str, CompanyMaskPlan] = field(default_factory=dict, repr=False)

    def discover(
        self,
        text: str,
        admin_candidates: Iterable[Candidate] = (),
        llm_analysis: dict | None = None,
        *,
        respect_fact_section_boundary: bool = True,
    ) -> list[MappingEntry]:
        scan_text = text
        if respect_fact_section_boundary:
            boundary_match = FACT_SECTION_BOUNDARY_RE.search(text)
            if boundary_match:
                scan_text = text[: boundary_match.start()]

        self.source_text = scan_text
        candidates = self.collect_candidates(scan_text, admin_candidates, llm_analysis or {})
        candidates = self._apply_llm_verdicts(candidates, scan_text, llm_analysis or {})
        candidates = resolve_candidate_overlaps(candidates)

        for candidate in sorted(candidates, key=lambda item: (item.start, -item.length, -item.confidence)):
            if (
                candidate.text in self.sample_blacklist
                and not self._llm_exact_overrides_sample_blacklist(candidate.type, candidate.text, candidate)
            ):
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

    def collect_candidates(
        self,
        text: str,
        admin_candidates: Iterable[Candidate],
        analysis: dict,
    ) -> list[Candidate]:
        candidates = list(admin_candidates)
        has_local_org_ner = any(
            candidate.type == "organization" and candidate.source.startswith("hanlp_ner")
            for candidate in candidates
        )
        party_candidates, _ = detect_party_candidates(text)
        candidates.extend(party_candidates)
        candidates.extend(detect_title_candidates(text))

        if self.use_semantic_rules:
            candidates.extend(detect_fallback_person_candidates(text))
            if self.use_china_admin_rules:
                candidates.extend(detect_china_admin_rule_candidates(text))

            if not has_local_org_ner:
                for match in ORG_FULL_RE.finditer(text):
                    value = _clean_organization_text(match.group(0))
                    if "与" in value:
                        value = value.rsplit("与", 1)[-1]
                    if value:
                        start = match.start() + match.group(0).find(value)
                        candidates.append(
                            Candidate(
                                type="organization",
                                text=value,
                                start=start,
                                end=start + len(value),
                                source="linear_full_org",
                                confidence=0.9,
                                risk_level="medium",
                                auto_redact=True,
                            )
                        )
                for match in BARE_COMPANY_ALIAS_RE.finditer(text):
                    value = _clean_organization_text(match.group("alias"))
                    if value and not _is_false_org(value):
                        start = match.start("alias")
                        candidates.append(
                            Candidate(
                                type="organization",
                                text=value,
                                start=start,
                                end=start + len(value),
                                source="linear_bare_org_alias",
                                confidence=0.91,
                                risk_level="medium",
                                auto_redact=True,
                            )
                        )

        candidates.extend(self._llm_candidates(text, analysis))
        return self._deduplicate_candidates(candidates)

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
            if candidate.text in rejected:
                continue
            calibrated = calibrations.get(candidate.text)
            if not isinstance(calibrated, str):
                reviewed.append(candidate)
                continue
            calibrated = calibrated.strip()
            if len(calibrated) < 2:
                continue
            nearby_start = max(0, candidate.start - 80)
            nearby_end = min(len(text), candidate.end + 80)
            start = text.find(calibrated, nearby_start, nearby_end)
            if start < 0:
                reviewed.append(candidate)
                continue
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
        return reviewed

    def _llm_candidates(self, text: str, analysis: dict) -> list[Candidate]:
        candidates: list[Candidate] = []
        windows = analysis.get("_sentence_windows", [])
        window_by_id = {
            item.get("id"): item
            for item in windows
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        } if isinstance(windows, list) else {}
        for item in analysis.get("locations", []):
            for value in self._entity_values(item, "full", "name", "text"):
                self._append_exact_candidate(candidates, text, value, "location", item, window_by_id)
        for item in analysis.get("persons", []):
            for value in self._entity_values(item, "name", "text"):
                self._append_exact_candidate(candidates, text, value, "person", item, window_by_id)
        for item in analysis.get("companies", []):
            for value in self._entity_values(item, "name", "full", "brand", "text"):
                self._append_exact_candidate(candidates, text, value, "organization", item, window_by_id)
            variants = item.get("variants", [])
            if isinstance(variants, list):
                for value in variants:
                    self._append_exact_candidate(candidates, text, value, "organization", item, window_by_id)
        for item in analysis.get("projects", []):
            for value in self._entity_values(item, "name", "full", "text"):
                self._append_exact_candidate(candidates, text, value, "project", item, window_by_id)
        return candidates

    @staticmethod
    def _entity_values(item: dict, *keys: str) -> list[str]:
        values: list[str] = []
        if not isinstance(item, dict):
            return values
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip() and value not in values:
                values.append(value)
        return values

    @staticmethod
    def _append_exact_candidate(
        candidates: list[Candidate],
        text: str,
        value: object,
        entity_type: str,
        item: dict | None = None,
        window_by_id: dict[str, dict] | None = None,
    ) -> None:
        if not isinstance(value, str) or len(value) < 2:
            return
        start = -1
        had_window = False
        if item and window_by_id:
            window_id = item.get("window")
            if isinstance(window_id, str):
                window = window_by_id.get(window_id)
                if window:
                    try:
                        span_start = int(window.get("start", 0))
                        span_end = int(window.get("end", 0))
                    except (TypeError, ValueError):
                        span_start = 0
                        span_end = 0
                    if span_end > span_start:
                        had_window = True
                        start = text.find(value, span_start, span_end)
        if start < 0 and had_window:
            occurrences = [match.start() for match in re.finditer(re.escape(value), text)]
            if len(occurrences) == 1 and entity_type in {"person", "location", "project"}:
                start = occurrences[0]
        elif start < 0 and not had_window:
            start = text.find(value)
        if start < 0:
            return
        candidates.append(
            Candidate(
                type=entity_type,
                text=value,
                start=start,
                end=start + len(value),
                source="linear_llm_exact",
                confidence=0.95,
                risk_level="medium",
                auto_redact=True,
            )
        )

    @staticmethod
    def _deduplicate_candidates(candidates: list[Candidate]) -> list[Candidate]:
        best: dict[tuple[str, str, int], Candidate] = {}
        for candidate in candidates:
            key = (candidate.type, candidate.text, candidate.start)
            previous = best.get(key)
            if previous is None or candidate.confidence > previous.confidence:
                best[key] = candidate
        return list(best.values())

    def accept_location(self, candidate: Candidate) -> None:
        if not self.profile.redact_locations:
            return
        value = candidate.text.strip()
        if _looks_like_false_location(self.source_text, candidate.start, candidate.end, value):
            return
        if is_compound_admin_path(value):
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
            or not re.fullmatch(r"[\u4e00-\u9fa5·]{2,6}", value)
            or _is_false_person(value)
            or any(word in value for word in ("当事", "应予", "应当", "予以"))
        ):
            return
        self.known_people.add(value)
        masked = f"{value[0]}某{self.counters.next(f'person_{value[0]}')}"
        self._add("person", value, masked, candidate)

    def accept_organization(self, candidate: Candidate) -> None:
        if not self.profile.redact_organizations:
            return
        raw_value = candidate.text.strip(" ：:，,。；;\n\t")
        value = _clean_organization_text(raw_value)
        if not value and candidate.source.startswith("linear_llm"):
            value = raw_value
        if not value or value in self.known_organizations:
            return
        if is_noisy_org_capture(value):
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
            if candidate.source.startswith("linear_llm") and len(value) >= 2 and not _is_false_org(f"{value}公司"):
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

        plan = build_company_mask_plan(
            value=value,
            source_text=self.source_text,
            known_locations=self.known_locations,
            get_location_prefix=self.get_location_prefix,
            next_brand_mask=lambda: self.counters.next("group_prefix"),
        )
        if plan is None:
            return

        for province, location_mask in plan.location_updates:
            self.known_locations[province] = location_mask
            self._add("location", province, location_mask, candidate)

        self.known_organizations.add(value)
        self._alias_cores_cache[value] = derived_organization_alias_cores(value)
        self._organization_plans[value] = plan
        self._add("organization", value, plan.full_mask, candidate)

        for alias in plan.aliases:
            self._add("organization", alias, alias_mask_for_organization(alias, plan), candidate)
        if has_explicit_bare_brand_alias(self.source_text, plan.brand):
            self._add("organization", plan.brand, plan.brand_mask, candidate)

        company_alias = f"{plan.brand}公司"
        if company_alias in self.source_text:
            self._add("organization", company_alias, f"{plan.brand_mask}公司", candidate)

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
            or (
                original in self.sample_blacklist
                and not self._llm_exact_overrides_sample_blacklist(entity_type, original, candidate)
            )
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
            )
        )

    @staticmethod
    def _llm_exact_overrides_sample_blacklist(
        entity_type: str,
        original: str,
        candidate: Candidate,
    ) -> bool:
        if candidate.source != "linear_llm_exact":
            return False
        if entity_type == "person":
            return bool(re.fullmatch(r"[\u4e00-\u9fa5·]{2,6}", original))
        if entity_type == "organization":
            return any(original.endswith(suffix) for suffix in LEGAL_SUFFIXES + INSTITUTION_SUFFIXES)
        return False