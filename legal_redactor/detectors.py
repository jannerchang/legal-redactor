"""Deterministic structured-identifier detection and signature stripping."""

from __future__ import annotations

import re

from .config import HIGH_RISK_TYPES
from .models import Candidate


PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d(?:[-\s]?\d){8}(?!\d)")
ID_RE = re.compile(
    r"(?<![0-9Xx])\d{6}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])"
    r"(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![0-9Xx])"
)
USCC_RE = re.compile(r"(?<![A-Z0-9])[0-9A-Z]{18}(?![A-Z0-9])")
EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9._%+-])"
)
BANK_RE = re.compile(r"(?<!\d)(?:\d[ -]?){16,24}(?!\d)")
CASE_RE = re.compile(
    r"[（(][12]\d{3}[）)]"
    r"[\u4e00-\u9fa5A-Za-z0-9]{1,16}?"
    r"(?P<proc>知民初|知民终|执异|执复|民辖终|民辖初|民辖|民初|民终|民申|民再|行初|行终|行申|刑初|刑终|刑申|刑再|商初|商终|破申|执|民撤|民特|民保|强清|管辖)"
    r"(?:[0-9一二三四五六七八九十百千万]+\s*号)?"
)


def risk_for(entity_type: str) -> str:
    return "high" if entity_type in HIGH_RISK_TYPES or entity_type == "email" else "medium"


def detect_standard_regex_candidates(text: str) -> list[Candidate]:
    """Detect the fixed structured identifiers supported without semantic inference."""
    candidates: list[Candidate] = []
    candidates.extend(
        _sensitive_regex_candidates(
            text,
            PHONE_RE,
            "phone",
            "regex",
            1.0,
            "手机号规则",
        )
    )
    candidates.extend(
        _sensitive_regex_candidates(
            text,
            ID_RE,
            "id_number",
            "regex",
            1.0,
            "身份证号规则",
        )
    )
    candidates.extend(_uscc_candidates(text))
    candidates.extend(_bank_candidates(text))
    candidates.extend(
        _sensitive_regex_candidates(
            text,
            EMAIL_RE,
            "email",
            "regex",
            1.0,
            "邮箱规则",
        )
    )
    candidates.extend(_case_candidates(text, source="court_case_number_parser"))
    return candidates


def detect_regex_candidates(text: str, include_addresses: bool = False) -> list[Candidate]:
    """Backward-compatible alias for the narrow structured-identifier detector."""
    _ = include_addresses
    return detect_standard_regex_candidates(text)


def _sensitive_regex_candidates(
    text: str,
    pattern: re.Pattern[str],
    entity_type: str,
    source: str,
    confidence: float,
    reason: str,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for match in pattern.finditer(text):
        start, end = _expand_sensitive_label(text, match.start(), match.end(), entity_type)
        candidates.append(
            Candidate(
                type=entity_type,
                text=text[start:end],
                start=start,
                end=end,
                source=source,
                confidence=confidence,
                risk_level=risk_for(entity_type),
                auto_redact=True,
                reason=reason,
            )
        )
    return candidates


def _expand_sensitive_label(text: str, start: int, end: int, entity_type: str) -> tuple[int, int]:
    prefixes = {
        "phone": ("联系电话", "电话号码", "手机号", "手机", "电话"),
        "id_number": ("公民身份号码", "身份证号码", "身份证号"),
        "unified_social_credit_code": ("统一社会信用代码",),
        "bank_account": ("银行账号", "银行账户", "收款账号", "账号", "账户"),
        "email": ("电子邮箱", "邮箱"),
    }.get(entity_type, ())
    lookback_start = max(0, start - 12)
    before = text[lookback_start:start]
    for prefix in sorted(prefixes, key=len, reverse=True):
        if before.endswith(prefix):
            return start - len(prefix), end
    return start, end



def _uscc_candidates(text: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    for match in USCC_RE.finditer(text):
        value = match.group(0)
        if ID_RE.fullmatch(value):
            continue
        if not re.fullmatch(r"[159Y][1239][0-9A-HJ-NPQRTUWXY]{16}", value):
            continue
        start, end = _expand_sensitive_label(
            text,
            match.start(),
            match.end(),
            "unified_social_credit_code",
        )
        candidates.append(
            Candidate(
                type="unified_social_credit_code",
                text=text[start:end],
                start=start,
                end=end,
                source="regex",
                confidence=1.0,
                risk_level="high",
                auto_redact=True,
                reason="统一社会信用代码规则",
            )
        )
    return candidates


def _bank_candidates(text: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    for match in BANK_RE.finditer(text):
        value = match.group(0).strip()
        digits = re.sub(r"\D", "", value)
        if not 16 <= len(digits) <= 24 or ID_RE.fullmatch(digits):
            continue
        start, end = _expand_sensitive_label(
            text,
            match.start(),
            match.start() + len(value),
            "bank_account",
        )
        candidates.append(
            Candidate(
                type="bank_account",
                text=text[start:end],
                start=start,
                end=end,
                source="regex",
                confidence=0.98,
                risk_level="high",
                auto_redact=True,
                reason="银行账号规则",
            )
        )
    return candidates


def _case_candidates(text: str, source: str) -> list[Candidate]:
    return [
        Candidate(
            type="case_number",
            text=match.group(0),
            start=match.start(),
            end=match.end(),
            source=source,
            confidence=1.0,
            risk_level="high",
            auto_redact=True,
            reason="案号结构化规则",
            metadata={"procedure": match.group("proc")},
        )
        for match in CASE_RE.finditer(text)
    ]


_COURT_PERSONNEL_ROLES = (
    "审判长",
    "审判员",
    "代理审判员",
    "人民陪审员",
    "法官助理",
    "书记员",
    "执行员",
    "执行法官",
    "法 官 助 理",
    "书 记 员",
    "审 判 长",
    "审 判 员",
)
_COURT_SIGNATURE_RE = re.compile(
    r"(?:^|\n)\s*(?:" + "|".join(_COURT_PERSONNEL_ROLES) + r")[\s：:]*[一-龥·\s]{2,20}(?:\n|$)",
    re.MULTILINE,
)


def remove_court_signatures(text: str) -> str:
    """Remove court-personnel signature lines from the rendered document."""
    lines = text.split("\n")
    if not any(_COURT_SIGNATURE_RE.match(line) for line in reversed(lines)):
        return text
    return "\n".join(
        line
        for line in lines
        if not (
            _COURT_SIGNATURE_RE.match(line.strip())
            or (
                any(line.strip().startswith(role) for role in _COURT_PERSONNEL_ROLES)
                and len(line.strip()) < 30
            )
        )
    )
