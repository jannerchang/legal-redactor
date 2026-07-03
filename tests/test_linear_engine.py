from __future__ import annotations

from dataclasses import dataclass

from legal_redactor.counters import TypeCounters
from legal_redactor.candidate_resolution import resolve_candidate_overlaps
from legal_redactor.linear_engine import LinearRuleEngine
from legal_redactor.org_masking import (
    derived_organization_alias_cores,
    explicit_organization_aliases,
    has_explicit_bare_brand_alias,
)
from legal_redactor.location_utils import get_location_core, location_suffix, strip_leading_locations
from legal_redactor.models import Candidate, MappingEntry, sort_mapping_entries


@dataclass
class _Profile:
    redact_locations: bool = True
    redact_persons: bool = True
    redact_organizations: bool = True
    redact_projects: bool = True


def _engine(*, sample_blacklist: set[str] | None = None, llm_primary_discovery: bool = False) -> LinearRuleEngine:
    counters = TypeCounters()
    prefixes: dict[str, str] = {}

    def get_location_prefix(name: str) -> str:
        core = get_location_core(name)
        if core not in prefixes:
            prefixes[core] = counters.next("location")
        return prefixes[core]

    return LinearRuleEngine(
        counters=counters,
        profile=_Profile(),
        sample_blacklist=sample_blacklist or set(),
        get_location_prefix=get_location_prefix,
        llm_primary_discovery=llm_primary_discovery,
    )


def test_get_location_core_recursively_strips_admin_suffixes() -> None:
    assert get_location_core("起航小镇") == "起航小镇"
    assert get_location_core("石家庄市裕华区") == "石家庄市裕华"
    assert get_location_core("河北省") == "河北"
    assert get_location_core("河北省石家庄市") == "河北省石家庄"


def test_location_suffix_prefers_longest_admin_suffix() -> None:
    assert location_suffix("河北省") == "省"
    assert location_suffix("祥云御福澜庭") == "地"


def test_strip_leading_locations_removes_multiple_known_prefixes() -> None:
    known = {
        "河北省": "甲省",
        "石家庄市": "乙市",
    }
    prefix, body = strip_leading_locations("河北省石家庄市星河建设有限公司", known)
    assert prefix == "甲省乙市"
    assert body == "星河建设有限公司"


def test_derived_organization_alias_cores_includes_brand_and_number_aliases() -> None:
    cores = derived_organization_alias_cores("河北省电力建设第二工程公司")
    assert "电建" in cores
    assert "二建" in cores


def test_explicit_organization_aliases_finds_former_name_and_short_name() -> None:
    text = (
        "石家庄裕华精密铸造有限公司（原名称：鹿泉市裕华精密铸造有限公司）签订合同，"
        "以下简称裕华公司。"
    )
    aliases = explicit_organization_aliases(text, "石家庄裕华精密铸造有限公司")
    assert "鹿泉市裕华精密铸造有限公司" in aliases
    assert "裕华公司" in aliases


def test_explicit_organization_aliases_finds_bare_short_name() -> None:
    text = "华北制药股份有限公司（以下简称华药）与中技公司签订合同。华药确认事实。"

    aliases = explicit_organization_aliases(text, "华北制药股份有限公司")

    assert "华药" in aliases


def test_explicit_organization_aliases_does_not_cross_contaminate_party_short_names() -> None:
    text = (
        "河北云厚建筑装饰工程有限公司（以下简称云厚公司）与"
        "河北兴代建筑安装工程有限公司（以下简称兴代公司）及"
        "石家庄方卫信息系统技术有限公司（以下简称方卫公司）签订合同。"
    )

    assert explicit_organization_aliases(text, "云厚公司") == []
    assert explicit_organization_aliases(text, "兴代公司") == []
    assert explicit_organization_aliases(text, "河北云厚建筑装饰工程有限公司") == ["云厚公司"]
    assert explicit_organization_aliases(text, "河北兴代建筑安装工程有限公司") == ["兴代公司"]


def test_has_explicit_bare_brand_alias_detects_parenthetical_short_name() -> None:
    text = "河北豪木山运输有限公司（以下简称豪木山）签订合同。"
    assert has_explicit_bare_brand_alias(text, "豪木山") is True
    assert has_explicit_bare_brand_alias(text, "豪木山运输") is False


def test_accept_location_maps_full_name_and_core() -> None:
    engine = _engine()
    candidate = Candidate(
        type="location",
        text="河北省",
        start=0,
        end=3,
        source="test",
        confidence=0.9,
        risk_level="low",
        auto_redact=True,
    )
    engine.source_text = "河北省某公司"
    engine.accept_location(candidate)

    originals = {mapping.original for mapping in engine.mappings}
    assert "河北省" in originals


def test_accept_person_masks_repeated_name() -> None:
    engine = _engine()
    engine.source_text = "原告张云峰提交证据。张云峰到庭。"
    for start in (2, 11):
        engine.accept_person(
            Candidate(
                type="person",
                text="张云峰",
                start=start,
                end=start + 3,
                source="party_section",
                confidence=0.95,
                risk_level="low",
                auto_redact=True,
            )
        )
    assert len(engine.mappings) == 1
    assert engine.mappings[0].masked.startswith("张某")


def test_accept_organization_skips_bare_brand_without_alias_context() -> None:
    engine = _engine()
    engine.source_text = "石家庄誉烁建筑工程有限公司签订合同。"
    engine.accept_organization(
        Candidate(
            type="organization",
            text="石家庄誉烁建筑工程有限公司",
            start=0,
            end=14,
            source="linear_full_org",
            confidence=0.9,
            risk_level="medium",
            auto_redact=True,
        )
    )
    originals = {mapping.original for mapping in engine.mappings}
    assert "石家庄誉烁建筑工程有限公司" in originals
    assert "石家庄誉烁" not in originals


def test_accept_organization_adds_bare_brand_with_explicit_alias_context() -> None:
    engine = _engine()
    engine.source_text = "河北豪木山运输有限公司（以下简称豪木山）签订合同。豪木山负责运输。"
    engine.accept_organization(
        Candidate(
            type="organization",
            text="河北豪木山运输有限公司",
            start=0,
            end=12,
            source="linear_full_org",
            confidence=0.9,
            risk_level="medium",
            auto_redact=True,
        )
    )
    originals = {mapping.original for mapping in engine.mappings}
    assert "河北豪木山运输有限公司" in originals
    assert "豪木山" in originals


def test_accept_organization_masks_institution_with_known_location() -> None:
    engine = _engine()
    engine.known_locations = {"河北省": "甲省", "河北": "甲省"}
    engine.source_text = "中国建设银行河北省分行签订合同。"
    engine.accept_organization(
        Candidate(
            type="organization",
            text="中国建设银行河北省分行",
            start=0,
            end=12,
            source="linear_full_org",
            confidence=0.9,
            risk_level="medium",
            auto_redact=True,
        )
    )
    assert engine.mappings
    assert engine.mappings[0].masked == "中国建设银行甲省分行"


def test_apply_llm_verdicts_rejects_and_calibrates_candidates() -> None:
    text = "办公区完成调整，某人无权代表星河公司签字。"
    candidate = Candidate(
        type="organization",
        text="某人无权代表星河公司",
        start=text.index("某人"),
        end=text.index("公司") + 2,
        source="test",
        confidence=0.8,
        risk_level="medium",
        auto_redact=True,
    )
    analysis = {
        "reject": ["办公区"],
        "calibrate": {"某人无权代表星河公司": "星河公司"},
    }
    reviewed = LinearRuleEngine._apply_llm_verdicts([candidate], text, analysis)
    assert [item.text for item in reviewed] == ["星河公司"]


def test_resolve_candidate_overlaps_prefers_higher_priority_source() -> None:
    organization = Candidate(
        type="organization",
        text="星河建设有限公司",
        start=10,
        end=18,
        source="party_section",
        confidence=0.95,
        risk_level="low",
        auto_redact=True,
    )
    person = Candidate(
        type="person",
        text="星河建设有限公司",
        start=10,
        end=18,
        source="hanlp_ner",
        confidence=0.99,
        risk_level="medium",
        auto_redact=True,
    )
    resolved = resolve_candidate_overlaps([person, organization])
    assert len(resolved) == 1
    assert resolved[0].source == "party_section"


def test_append_exact_candidate_skips_ambiguous_global_find_when_window_misses() -> None:
    text = "甲公司提交说明。乙公司到庭。"
    candidates: list[Candidate] = []
    LinearRuleEngine._append_exact_candidate(
        candidates,
        text,
        "乙公司",
        "organization",
        {"window": "s2"},
        {
            "s2": {"start": 0, "end": 6},
        },
    )
    assert candidates == []


def test_append_exact_candidate_uses_single_occurrence_fallback_when_window_misses() -> None:
    text = "原告江苏路达电力工程有限公司，后更名为淮安载道电力工程有限公司。张三住河北省石家庄市长安区。"
    candidates: list[Candidate] = []
    LinearRuleEngine._append_exact_candidate(
        candidates,
        text,
        "张三",
        "person",
        {"window": "s1"},
        {"s1": {"start": 0, "end": 32}},
    )
    assert len(candidates) == 1
    assert candidates[0].text == "张三"
    assert candidates[0].start == text.index("张三")


def test_resolve_candidate_overlaps_prefers_clean_nested_org_alias() -> None:
    outer = Candidate(
        type="organization",
        text="到的拓欧公司",
        start=18,
        end=24,
        source="linear_full_org",
        confidence=0.9,
        risk_level="medium",
        auto_redact=True,
    )
    inner = Candidate(
        type="organization",
        text="拓欧公司",
        start=20,
        end=24,
        source="linear_bare_org_alias",
        confidence=0.91,
        risk_level="medium",
        auto_redact=True,
    )
    resolved = resolve_candidate_overlaps([outer, inner])
    assert len(resolved) == 1
    assert resolved[0].text == "拓欧公司"


def test_llm_primary_discovery_skips_party_and_regex_candidates() -> None:
    engine = _engine(llm_primary_discovery=True)
    analysis = {
        "companies": [{"window": "s1", "name": "兴代公司", "variants": ["兴代公司"]}],
        "persons": [],
        "locations": [],
        "projects": [],
        "reject": ["否认其与兴代公司系关联公司"],
        "calibrate": {},
        "_sentence_windows": [{"id": "s1", "previous": "", "target": "被告否认其与兴代公司系关联公司。", "next": ""}],
    }
    text = "被告否认其与兴代公司系关联公司，兴代公司辩称无关联。"
    mappings = engine.discover(text, llm_analysis=analysis)
    originals = {mapping.original for mapping in mappings}
    assert "兴代公司" in originals
    assert "否认其与兴代公司系关联公司" not in originals


def test_discover_rejects_false_org_clause_with_embedded_company() -> None:
    engine = _engine()
    text = "被告否认其与兴代公司系关联公司，兴代公司辩称双方无关联。"
    mappings = engine.discover(text)
    originals = {mapping.original for mapping in mappings}
    assert "否认其与兴代公司系关联公司" not in originals
    assert "兴代公司" in originals


def test_discover_respects_sample_blacklist_for_rules() -> None:
    engine = _engine(sample_blacklist={"办公区"})
    text = "办公区完成调整，河北星河建筑工程有限公司签订合同。"
    mappings = engine.discover(text)
    originals = {mapping.original for mapping in mappings}
    assert "办公区" not in originals
    assert "河北星河建筑工程有限公司" in originals


def test_sentence_windows_keep_commas_inside_sentence() -> None:
    from legal_redactor.llm import build_sentence_windows

    windows = build_sentence_windows("原告张三、李四，被告王五。")

    assert len(windows) == 1
    assert windows[0]["target"] == "原告张三、李四，被告王五。"


def test_sentence_windows_keep_one_sentence_per_target() -> None:
    from legal_redactor.llm import build_sentence_windows

    windows = build_sentence_windows("原告张三提交证据。被告李四发表意见！第三人王五未到庭？")

    assert [item["target"] for item in windows] == [
        "原告张三提交证据。",
        "被告李四发表意见！",
        "第三人王五未到庭？",
    ]
    assert windows[1]["previous"] == "原告张三提交证据。"
    assert windows[1]["next"] == "第三人王五未到庭？"


def test_sentence_extraction_partial_batch_failure_keeps_successful_batches() -> None:
    from legal_redactor.config import LocalLLMConfig
    from legal_redactor.llm import LegalEntityAuditor

    auditor = LegalEntityAuditor(LocalLLMConfig(mode="max-effect"))
    text = "".join(f"第{i}句原告张三提交证据。" for i in range(1, 22))
    calls: list[str] = []

    def fake_extract_windows_batch(batch, *, enable_samples, label):
        calls.append(label)
        if label.startswith("batch 2/"):
            return None, [f"{label}: simulated failure"]
        return {
            "locations": [],
            "companies": [],
            "persons": [{"window": batch[0]["id"], "name": "张三"}],
            "projects": [],
            "reject": [],
            "calibrate": {},
        }, []

    auditor._extract_windows_batch = fake_extract_windows_batch  # type: ignore[method-assign]

    result = auditor.extract_sentence_entities(text, enable_samples=False)

    assert "error" not in result
    assert result["_batch_failures"] == ["batch 2/3: simulated failure"]
    assert [item["name"] for item in result["persons"]] == ["张三"]
    assert sorted(calls) == ["batch 1/3", "batch 2/3", "batch 3/3"]


def test_sentence_batch_records_one_failure_after_retry() -> None:
    from legal_redactor.config import LocalLLMConfig
    from legal_redactor.llm import LegalEntityAuditor

    auditor = LegalEntityAuditor(LocalLLMConfig(mode="max-effect"))

    def fail_call(prompt, *, max_tokens):
        raise RuntimeError("bad json")

    auditor._call_local_model = fail_call  # type: ignore[method-assign]

    payload, failures = auditor._extract_windows_batch(
        [{"id": "s1", "previous": "", "target": "原告张三。", "next": ""}],
        enable_samples=False,
        label="batch 1/1",
    )

    assert payload is None
    assert failures == ["batch 1/1: bad json"]


def test_sentence_orchestration_keeps_company_names_from_llm_clause_output() -> None:
    from legal_redactor.llm import orchestrate_sentence_extractions

    sentence = (
        "石家庄裕华精密铸造有限公司（原名称：鹿泉市裕华精密铸造有限公司），"
        "后有简称为：裕华公司。"
    )
    analysis = {
        "locations": [],
        "companies": [
            {
                "window": "s1",
                "name": (
                    "石家庄裕华精密铸造有限公司（原名称：鹿泉市裕华精密铸造有限公司），"
                    "后有简称为：裕华公司"
                ),
            }
        ],
        "persons": [],
        "projects": [],
        "reject": [],
        "calibrate": {},
    }

    result = orchestrate_sentence_extractions(analysis, source_text=sentence)

    variants = set(result["companies"][0]["variants"])
    assert "石家庄裕华精密铸造有限公司" in variants
    assert "鹿泉市裕华精密铸造有限公司" in variants
    assert "裕华公司" in variants


def test_sentence_orchestration_strips_litigation_role_company_prefix() -> None:
    from legal_redactor.llm import orchestrate_sentence_extractions

    result = orchestrate_sentence_extractions(
        {
            "locations": [],
            "companies": [
                {
                    "window": "s1",
                    "name": "被告河北星河建设有限公司",
                    "variants": ["被告河北星河建设有限公司", "星河建设公司"],
                }
            ],
            "persons": [],
            "projects": [],
            "reject": [],
            "calibrate": {},
        }
    )

    assert result["companies"] == [
        {
            "window": "s1",
            "name": "河北星河建设有限公司",
            "variants": ["河北星河建设有限公司", "星河建设公司"],
        }
    ]


def test_sentence_orchestration_drops_action_clause_organization_noise() -> None:
    from legal_redactor.llm import orchestrate_sentence_extractions

    result = orchestrate_sentence_extractions(
        {
            "locations": [],
            "companies": [
                {"window": "s1", "name": "王琳向冯朋嵩发送河北银行", "variants": ["王琳向冯朋嵩发送河北银行"]},
                {"window": "s2", "name": "否认冯朋嵩系兴代公司", "variants": ["否认冯朋嵩系兴代公司"]},
                {"window": "s3", "name": "称冯朋嵩以兴代公司", "variants": ["称冯朋嵩以兴代公司"]},
                {"window": "s4", "name": "云厚公司", "variants": ["云厚公司"]},
            ],
            "persons": [],
            "projects": [],
            "reject": [],
            "calibrate": {},
        }
    )

    company_names = {item["name"] for item in result["companies"]}
    assert "云厚公司" in company_names
    assert "河北银行" in company_names
    assert "兴代公司" in company_names
    assert "王琳向冯朋嵩发送河北银行" not in company_names
    assert "否认冯朋嵩系兴代公司" not in company_names
    assert "称冯朋嵩以兴代公司" not in company_names


def test_sentence_orchestration_drops_generic_project_noise() -> None:
    from legal_redactor.llm import orchestrate_sentence_extractions

    result = orchestrate_sentence_extractions(
        {
            "locations": [],
            "companies": [],
            "persons": [],
            "projects": [
                {"window": "s1", "name": "办公大厅整体装修施工"},
                {"window": "s2", "name": "会议室装修承包合同"},
                {"window": "s3", "name": "二期空调采购清单"},
                {"window": "s4", "name": "合同总款"},
                {"window": "s5", "name": "整体工程"},
                {"window": "s6", "name": "报价单"},
                {"window": "s7", "name": "起航小镇"},
            ],
            "reject": [],
            "calibrate": {},
        }
    )

    assert result["projects"] == [{"window": "s7", "name": "起航小镇"}]


def test_mapping_sort_groups_entity_types_for_review() -> None:
    mappings = [
        MappingEntry("project", "起航小镇", "甲小镇", None, "test", 1.0, True),
        MappingEntry("organization", "云厚公司", "甲公司", None, "test", 1.0, True),
        MappingEntry("location", "石家庄市", "甲市", None, "test", 1.0, True),
        MappingEntry("person", "张三", "张某甲", None, "test", 1.0, True),
    ]

    assert [item.type for item in sort_mapping_entries(mappings)] == [
        "organization",
        "location",
        "person",
        "project",
    ]


def test_discover_detects_inline_party_person_lists() -> None:
    engine = _engine()
    text = (
        "原告华北制药股份有限公司诉被告张三、李四，"
        "第三人赵仁川、王利杰、王兴国、张熠焯、崔松豪、余湘北合同纠纷一案。"
    )

    mappings = engine.discover(text)

    originals = {mapping.original for mapping in mappings}
    assert {"张三", "李四", "赵仁川", "王利杰", "王兴国", "张熠焯", "崔松豪", "余湘北"} <= originals


def test_discover_maps_explicit_bare_company_alias_as_organization() -> None:
    engine = _engine()
    text = "华北制药股份有限公司（以下简称华药）与中技公司签订合同。华药公司提交说明，华药确认事实。"

    mappings = engine.discover(text)

    by_original = {mapping.original: mapping for mapping in mappings}
    assert by_original["华药"].type == "organization"
    assert by_original["华药"].masked.endswith("公司")
    assert by_original["华药公司"].masked == by_original["华药"].masked


def test_apply_mappings_does_not_replace_bare_alias_inside_different_company() -> None:
    from legal_redactor.config import PipelineConfig
    from legal_redactor.pipeline import RedactionPipeline

    engine = _engine()
    text = (
        "华北制药股份有限公司（以下简称华药）提交说明。"
        "华药公司认可事实，华药生物公司另行提交材料，华药研发公司另行提交材料，华药继续陈述。"
    )
    mappings = engine.discover(text)
    by_original = {mapping.original: mapping for mapping in mappings}

    redacted = RedactionPipeline(config=PipelineConfig.offline_without_llm()).apply_mappings(text, mappings)

    assert by_original["华药公司"].masked == by_original["华药"].masked
    assert by_original["华药生物公司"].masked != by_original["华药"].masked
    assert by_original["华药研发公司"].masked != by_original["华药"].masked
    assert "华药公司" not in redacted
    assert "华药生物公司" not in redacted
    assert "华药研发公司" not in redacted
    assert "公司生物公司" not in redacted
    assert "公司研发公司" not in redacted
    assert "华药继续陈述" not in redacted


def test_apply_mappings_skips_bare_alias_inside_unmapped_company_name() -> None:
    from legal_redactor.config import PipelineConfig
    from legal_redactor.pipeline import RedactionPipeline

    text = "华药公司认可事实，华药生物公司另行提交材料，华药继续陈述。"
    mappings = [
        MappingEntry("organization", "华药公司", "甲公司", None, "test", 1.0, True),
        MappingEntry("organization", "华药", "甲公司", None, "test", 1.0, True),
    ]

    redacted = RedactionPipeline(config=PipelineConfig.offline_without_llm()).apply_mappings(text, mappings)

    assert "甲公司认可事实" in redacted
    assert "华药生物公司" in redacted
    assert "甲公司生物公司" not in redacted
    assert "甲公司继续陈述" in redacted


def test_accept_organization_reuses_brand_across_different_location_prefixes() -> None:
    engine = _engine()
    engine.source_text = (
        "原告江苏载道电力工程有限公司，后更名为淮安载道电力工程有限公司。"
        "载道公司亦参与诉讼。"
    )
    names = [
        "江苏载道电力工程有限公司",
        "淮安载道电力工程有限公司",
        "载道公司",
        "载道电力工程有限公司",
    ]
    for name in names:
        engine.accept_organization(
            Candidate(
                type="organization",
                text=name,
                start=engine.source_text.index(name),
                end=engine.source_text.index(name) + len(name),
                source="linear_llm_exact",
                confidence=0.95,
                risk_level="medium",
                auto_redact=True,
            )
        )

    by_original = {mapping.original: mapping.masked for mapping in engine.mappings}
    jiangsu = by_original["江苏载道电力工程有限公司"]
    huaian = by_original["淮安载道电力工程有限公司"]
    assert jiangsu.endswith("电力工程公司")
    assert huaian.endswith("电力工程公司")
    assert jiangsu != huaian
    assert jiangsu[2] == huaian[2] == by_original["载道公司"][0]
    assert by_original["载道公司"] == f"{jiangsu[2]}公司"


def test_accept_organization_reuses_brand_mask_for_short_and_full_names() -> None:
    engine = _engine()
    engine.source_text = (
        "河北云厚建筑装饰工程有限公司（以下简称云厚公司）与"
        "河北兴代建筑安装工程有限公司（以下简称兴代公司）及"
        "石家庄方卫信息系统技术有限公司（以下简称方卫公司）签订合同。"
    )
    names = [
        "云厚公司",
        "兴代公司",
        "方卫公司",
        "河北云厚建筑装饰工程有限公司",
        "河北兴代建筑安装工程有限公司",
        "石家庄方卫信息系统技术有限公司",
    ]
    for name in names:
        engine.accept_organization(
            Candidate(
                type="organization",
                text=name,
                start=engine.source_text.index(name),
                end=engine.source_text.index(name) + len(name),
                source="linear_llm_exact",
                confidence=0.95,
                risk_level="medium",
                auto_redact=True,
            )
        )

    by_original = {mapping.original: mapping.masked for mapping in engine.mappings}
    assert by_original["云厚公司"] == "甲公司"
    assert by_original["兴代公司"] == "乙公司"
    assert by_original["方卫公司"] == "丙公司"
    assert by_original["河北云厚建筑装饰工程有限公司"].startswith("甲省甲")
    assert by_original["河北兴代建筑安装工程有限公司"].startswith("甲省乙")
    assert by_original["石家庄方卫信息系统技术有限公司"].startswith("乙省丙")
    assert by_original["云厚公司"] == by_original["河北云厚建筑装饰工程有限公司"][2] + "公司"
    assert by_original["兴代公司"] == by_original["河北兴代建筑安装工程有限公司"][2] + "公司"
    assert by_original["方卫公司"] == by_original["石家庄方卫信息系统技术有限公司"][2] + "公司"


def test_accept_organization_keeps_different_company_short_names_separate() -> None:
    engine = _engine()
    engine.source_text = (
        "河北星河建设有限公司与北京星河科技有限公司签订合同。"
        "星河建设公司提交说明，星河科技公司提交说明。"
    )
    for name in (
        "河北星河建设有限公司",
        "北京星河科技有限公司",
        "星河建设公司",
        "星河科技公司",
    ):
        engine.accept_organization(
            Candidate(
                type="organization",
                text=name,
                start=engine.source_text.index(name),
                end=engine.source_text.index(name) + len(name),
                source="linear_llm_exact",
                confidence=0.95,
                risk_level="medium",
                auto_redact=True,
            )
        )

    by_original = {mapping.original: mapping.masked for mapping in engine.mappings}
    assert by_original["星河建设公司"] != by_original["星河科技公司"]
    assert by_original["星河建设公司"] == by_original["河北星河建设有限公司"][2] + "公司"
    assert by_original["星河科技公司"] == by_original["北京星河科技有限公司"][2] + "公司"


def test_merge_organization_alias_mappings_keeps_different_company_short_names_separate() -> None:
    from legal_redactor.pipeline import _merge_organization_alias_mappings

    mappings = [
        MappingEntry("organization", "河北星河建设有限公司", "甲省甲公司", None, "linear:linear_llm_exact", 0.95, True),
        MappingEntry("organization", "星河建设公司", "甲公司", None, "linear:linear_llm_exact", 0.95, True),
        MappingEntry("organization", "北京星河科技有限公司", "乙省乙科技公司", None, "linear:linear_llm_exact", 0.95, True),
        MappingEntry("organization", "星河科技公司", "乙公司", None, "linear:linear_llm_exact", 0.95, True),
    ]

    merged = _merge_organization_alias_mappings(mappings)
    by_original = {mapping.original: mapping.masked for mapping in merged}

    assert by_original["星河建设公司"] == "甲公司"
    assert by_original["星河科技公司"] == "乙公司"
    assert by_original["星河建设公司"] != by_original["星河科技公司"]
