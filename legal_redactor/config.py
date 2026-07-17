from __future__ import annotations

from dataclasses import dataclass, field
import os
from .model_manager import BONSAI_MODEL_ID



HIGH_RISK_TYPES = {
    "id_number",
    "phone",
    "bank_account",
    "address",
    "unified_social_credit_code",
    "case_number",
}

# ── 可量化的脱敏策略配置 ──────────────────────────────────────────


@dataclass(frozen=True)
class RedactionProfile:
    """默认只处理公开文书中的直接标识符与明确主体。

    泛地点、详细地址、项目和其他敏感类别保持原文；用户可在映射审核页
    手动选择补充脱敏。
    """

    name: str = "custom"

    # ── 核心目标 ──
    redact_persons: bool = True
    """人名（当事人、代理人、证人等）"""

    redact_locations: bool = True
    """仅自动处理行政区划省/市/区县；街道、乡镇、村和社区保留人工选择。"""

    redact_organizations: bool = True
    """机构/公司/律所/村委会等"""

    redact_projects: bool = False
    """项目/工程/楼盘名默认保留，需由用户手动选择。"""

    # ── 敏感编号 ──
    redact_id_numbers: bool = True
    """身份证号"""

    redact_phones: bool = True
    """手机/电话号码"""

    redact_bank_accounts: bool = False
    """银行账号默认保留，需由用户手动选择。"""

    redact_uscc: bool = False
    """统一社会信用代码默认保留，需由用户手动选择。"""

    redact_emails: bool = False
    """邮箱默认保留，需由用户手动选择。"""

    # ── 司法标识（默认不脱敏） ──
    redact_case_numbers: bool = False
    """案号"""

    redact_court_names: bool = False
    """法院名称"""

    redact_addresses: bool = False
    """详细地址默认保留，需由用户手动选择。"""

    # ── 行为控制 ──
    party_section_detail: bool = False
    """是否做当事人段的逐字段结构化解析（关闭则仅从中提取人名/机构名）"""

    skip_court_personnel: bool = True
    """跳过审判组织人员（审判长、审判员、书记员等）"""

    confidence_threshold: float = 0.60
    """低于此置信度的候选进入人工复核而非自动脱敏"""

    # ── 预设 ──

    @classmethod
    def minimal(cls) -> "RedactionProfile":
        """最小脱敏：仅人名、身份证号和手机号。"""
        return cls(
            name="minimal",
            redact_persons=True,
            redact_locations=False,
            redact_organizations=False,
            redact_projects=False,
            redact_id_numbers=True,
            redact_phones=True,
            redact_bank_accounts=False,
            redact_uscc=False,
            redact_emails=False,
            redact_case_numbers=False,
            redact_court_names=False,
            redact_addresses=False,
            party_section_detail=False,
            skip_court_personnel=True,
        )

    @classmethod
    def standard(cls) -> "RedactionProfile":
        """公开文书默认脱敏：主体、行政省市区与直接标识符。

        自动范围仅限人名、机构名称、行政区划省/市/区县、身份证号、手机号和案号。
        街道及以下地点、项目、详细地址、邮箱、银行账号和统一社会信用代码
        保持原文，用户可在映射审核页手动添加。
        """
        return cls(
            name="standard",
            redact_persons=True,
            redact_locations=True,
            redact_organizations=True,
            redact_projects=False,
            redact_id_numbers=True,
            redact_phones=True,
            redact_bank_accounts=False,
            redact_uscc=False,
            redact_emails=False,
            redact_case_numbers=True,
            redact_court_names=False,
            redact_addresses=False,
            party_section_detail=False,
            skip_court_personnel=True,
        )



    @classmethod
    def from_preset(cls, name: str) -> "RedactionProfile":
        if name == "normal":
            name = "standard"
        
        presets = {
            "minimal": cls.minimal,
            "standard": cls.standard,
            "accuracy-max-effect": cls.standard,
        }
        factory = presets.get(name)
        if factory is None:
            raise ValueError(f"未知脱敏策略：{name}，可选：minimal / standard")
        
        profile = factory()
        if name == "accuracy-max-effect":
            return cls(
                name="accuracy-max-effect",
                redact_persons=profile.redact_persons,
                redact_locations=profile.redact_locations,
                redact_organizations=profile.redact_organizations,
                redact_projects=profile.redact_projects,
                redact_id_numbers=profile.redact_id_numbers,
                redact_phones=profile.redact_phones,
                redact_bank_accounts=profile.redact_bank_accounts,
                redact_uscc=profile.redact_uscc,
                redact_emails=profile.redact_emails,
                redact_case_numbers=profile.redact_case_numbers,
                redact_court_names=profile.redact_court_names,
                redact_addresses=profile.redact_addresses,
                party_section_detail=profile.party_section_detail,
                skip_court_personnel=profile.skip_court_personnel,
            )
        return profile



DEFAULT_MODEL_MANAGER_HOST = "127.0.0.1"
DEFAULT_MODEL_MANAGER_PORT = 18080


@dataclass(frozen=True)
class LLMAPIConfig:
    enabled: bool = True
    role: str = "candidate_review_only"
    mode: str = "max-effect"
    model: str = BONSAI_MODEL_ID
    temperature: float = 0.0
    context_window: int = 32768
    output_format: str = "json"
    timeout_seconds: int = 120
    fail_open: bool = True
    model_manager_host: str = field(default_factory=lambda: os.environ.get("LEGAL_REDACTOR_MODEL_MANAGER_HOST", DEFAULT_MODEL_MANAGER_HOST))
    model_manager_port: int = field(default_factory=lambda: int(os.environ.get("LEGAL_REDACTOR_MODEL_MANAGER_PORT", str(DEFAULT_MODEL_MANAGER_PORT))))


@dataclass(frozen=True)
class PipelineConfig:
    semantic_llm_first: bool = False
    enable_regex: bool = True
    enable_hebei_admin_db: bool = True
    hebei_admin_db_path: str = "data/hebei_admin_divisions.sqlite"
    enable_china_admin_db: bool = True
    china_admin_db_path: str = "data/china_admin_divisions.sqlite"
    enable_china_admin_rules: bool = True
    enable_heuristic_ner: bool = True
    enable_hanlp_ner: bool = False
    hanlp_model: str = "MSRA_NER_ELECTRA_SMALL_ZH"
    hanlp_max_chars: int = 12000
    enable_llm: bool = True
    llm: LLMAPIConfig = field(default_factory=LLMAPIConfig)
    redaction_profile: RedactionProfile = field(default_factory=RedactionProfile.standard)

    @property
    def profile(self) -> str:
        return self.redaction_profile.name

    @classmethod
    def offline_without_llm(cls, profile_name: str = "standard") -> "PipelineConfig":
        llm = LLMAPIConfig(enabled=False)
        return cls(
            enable_llm=False,
            llm=llm,
            redaction_profile=RedactionProfile.from_preset(profile_name),
        )

    @classmethod
    def max_effect(cls, profile_name: str = "standard") -> "PipelineConfig":
        llm = LLMAPIConfig(
            enabled=True,
            role="sentence_entity_extraction",
            mode="max-effect",
            context_window=8192,
            timeout_seconds=120,
            fail_open=True,
        )
        return cls(
            semantic_llm_first=True,
            enable_llm=True,
            llm=llm,
            redaction_profile=RedactionProfile.from_preset(profile_name),
        )

    @classmethod
    def balanced_llm(cls, profile_name: str = "standard") -> "PipelineConfig":
        llm = LLMAPIConfig(
            enabled=True,
            role="sentence_entity_extraction",
            mode="balanced",
            context_window=8192,
            timeout_seconds=180,
            fail_open=False,
        )
        return cls(
            semantic_llm_first=True,
            enable_llm=True,
            llm=llm,
            redaction_profile=RedactionProfile.from_preset(profile_name),
        )

    @classmethod
    def from_llm_mode(cls, llm_mode: str, profile_name: str = "standard") -> "PipelineConfig":
        if llm_mode == "off":
            return cls.offline_without_llm(profile_name)
        if llm_mode == "balanced":
            return cls.balanced_llm(profile_name)
        if llm_mode == "max-effect":
            return cls.max_effect(profile_name)
        raise ValueError(f"unsupported llm mode: {llm_mode}")
