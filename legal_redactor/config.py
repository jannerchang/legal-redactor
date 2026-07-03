from __future__ import annotations

from dataclasses import dataclass, field


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
    """可量化的脱敏策略。

    每个字段独立开关，用户可根据场景精确选择：
      - 地名 + 人名（最小脱敏，适合快速去标识化）
      - 地名 + 人名 + 机构 + 编号（标准脱敏）
      - 全部（强脱敏，含金额、日期、地址等）
    """

    name: str = "custom"

    # ── 核心目标 ──
    redact_persons: bool = True
    """人名（当事人、代理人、证人等）"""

    redact_locations: bool = True
    """地名（行政区划、村/社区、街道等）"""

    redact_organizations: bool = True
    """机构/公司/律所/村委会等"""

    redact_projects: bool = False
    """项目/工程/楼盘名"""

    # ── 敏感编号 ──
    redact_id_numbers: bool = True
    """身份证号"""

    redact_phones: bool = True
    """手机/电话号码"""

    redact_bank_accounts: bool = True
    """银行账号"""

    redact_uscc: bool = True
    """统一社会信用代码"""

    redact_emails: bool = True
    """邮箱地址"""

    # ── 司法标识（默认不脱敏） ──
    redact_case_numbers: bool = False
    """案号"""

    redact_court_names: bool = False
    """法院名称"""

    # ── 扩展脱敏 ──
    redact_addresses: bool = False
    """详细地址（门牌号等）"""

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
        """最小脱敏：仅地名 + 人名 + 身份证号 + 手机号。

        适合快速去标识化，当事人段不做结构化解析，
        审判组织、案号、金额等一律保留。
        """
        return cls(
            name="minimal",
            redact_persons=True,
            redact_locations=True,
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
        """标准脱敏：最小 + 机构/公司/项目 + 敏感编号。

        当事人段不做详细结构解析（简单提取人名/机构名即可），
        审判组织不处理。
        """
        return cls(
            name="standard",
            redact_persons=True,
            redact_locations=True,
            redact_organizations=True,
            redact_projects=True,
            redact_id_numbers=True,
            redact_phones=True,
            redact_bank_accounts=True,
            redact_uscc=True,
            redact_emails=True,
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

MAX_EFFECT_LLM_MODEL = "mlx-community/Qwen3.5-9B-MLX-4bit"
MAX_EFFECT_FALLBACK_MODELS: tuple[str, ...] = ()
BALANCED_LLM_MODEL = MAX_EFFECT_LLM_MODEL
BALANCED_FALLBACK_MODELS: tuple[str, ...] = ()


@dataclass(frozen=True)
class LocalLLMConfig:
    enabled: bool = True
    role: str = "candidate_review_only"
    backend: str = "mlx"
    backend_priority: tuple[str, ...] = ("mlx",)
    mode: str = "max-effect"
    model: str = MAX_EFFECT_LLM_MODEL
    fallback_models: tuple[str, ...] = MAX_EFFECT_FALLBACK_MODELS
    temperature: float = 0.0
    context_window: int = 32768
    output_format: str = "json"
    timeout_seconds: int = 120
    fail_open: bool = True
    ollama_host: str = "127.0.0.1"
    ollama_port: int = 11434
    mlx_host: str = "127.0.0.1"
    mlx_port: int = 18080


@dataclass(frozen=True)
class PipelineConfig:
    strategy: str = "linear"
    replacement_order: str = "longest_first"
    semantic_llm_first: bool = False
    preserve_core_facts: bool = True
    human_review: bool = True
    fail_on_high_risk_leak: bool = True
    auto_accept_confidence: float = 0.92
    review_confidence_min: float = 0.50
    high_risk_auto_redact: bool = True
    high_risk_types: set[str] = field(default_factory=lambda: set(HIGH_RISK_TYPES))
    enable_regex: bool = True
    enable_party_parser: bool = True
    enable_title_parser: bool = True
    enable_hebei_admin_db: bool = True
    hebei_admin_db_path: str = "data/hebei_admin_divisions.sqlite"
    enable_china_admin_db: bool = True
    china_admin_db_path: str = "data/china_admin_divisions.sqlite"
    enable_china_admin_rules: bool = True
    enable_heuristic_ner: bool = True
    enable_hanlp_ner: bool = False
    hanlp_model: str = "MSRA_NER_ELECTRA_SMALL_ZH"
    hanlp_max_chars: int = 12000
    enable_local_llm: bool = True
    local_llm: LocalLLMConfig = field(default_factory=LocalLLMConfig)
    redaction_profile: RedactionProfile = field(default_factory=RedactionProfile.standard)
    enable_sample_library: bool = True

    @property
    def profile(self) -> str:
        return self.redaction_profile.name

    @classmethod
    def offline_without_llm(cls, profile_name: str = "standard") -> "PipelineConfig":
        llm = LocalLLMConfig(enabled=False)
        return cls(
            enable_local_llm=False,
            local_llm=llm,
            redaction_profile=RedactionProfile.from_preset(profile_name),
        )

    @classmethod
    def max_effect(cls, profile_name: str = "standard") -> "PipelineConfig":
        llm = LocalLLMConfig(
            role="sentence_entity_extraction",
            mode="max-effect",
            model=MAX_EFFECT_LLM_MODEL,
            fallback_models=MAX_EFFECT_FALLBACK_MODELS,
            context_window=8192,
            timeout_seconds=120,
            fail_open=True,
        )
        return cls(
            semantic_llm_first=True,
            local_llm=llm,
            redaction_profile=RedactionProfile.from_preset(profile_name),
        )

    @classmethod
    def balanced_llm(cls, profile_name: str = "standard") -> "PipelineConfig":
        llm = LocalLLMConfig(
            role="sentence_entity_extraction",
            mode="balanced",
            model=BALANCED_LLM_MODEL,
            fallback_models=BALANCED_FALLBACK_MODELS,
            context_window=8192,
            timeout_seconds=180,
            fail_open=False,
        )
        return cls(
            semantic_llm_first=True,
            local_llm=llm,
            redaction_profile=RedactionProfile.from_preset(profile_name),
        )

    @classmethod
    def from_llm_mode(cls, llm_mode: str, profile_name: str = "standard", model: str | None = None) -> "PipelineConfig":
        # model is kept for backward-compatible callers, but runtime selection is fixed.
        _ = model
        if llm_mode == "off":
            return cls.offline_without_llm(profile_name)
        if llm_mode == "balanced":
            return cls.balanced_llm(profile_name)
        return cls.max_effect(profile_name)
