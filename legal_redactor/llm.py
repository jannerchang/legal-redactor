from __future__ import annotations

import http.client
import json
import re
import time
from dataclasses import dataclass, field as dataclass_field
from json import JSONDecodeError

from ._logging import get_logger
from .config import LLMAPIConfig
from .entity_registry import (
    RegistryValidationResult,
    merge_full_document_registries,
    parse_full_document_registry,
    validate_registry_against_text,
)




_logger = get_logger("llm")



_AUDIT_MAX_TOKENS = 4096
_CONTRACT_NOISE_RE = re.compile(r"合同[一二三四五六七八九十百零\d]+")
_FALSE_ORG_CLAUSE_RE = re.compile(r"否认其与[^。！？\n，,、；;]{2,24}系关联公司")
_ORG_ACTION_CLAUSE_RE = re.compile(
    r"(?:否认|称|辩称|主张|认为|发送|出具|提交|告知|通知|转账|汇款|付款|支付|联系)"
    r"[^。！？\n，,、；;]{0,24}(?:公司|集团|银行|分行|支行|律所)$"
)
_ORG_RELATION_CLAUSE_RE = re.compile(
    r"^[\u4e00-\u9fa5]{2,6}(?:系|为|以|代表)[^。！？\n，,、；;]{2,16}(?:公司|集团|银行|分行|支行|律所)$"
)
_INVALID_COMPANY_VARIANT_RE = re.compile(
    r"(?:"
    r"^[我你他她其该此甲乙丙丁戊己庚辛壬癸][与和及向对给由从被把将]"
    r"|\d{4}年"
    r"|以下简称|下称|简称|原名称|曾用名|否认其"
    r")"
)

_DOCUMENT_OR_PROJECT_COMPANY_NOISE_RE = re.compile(
    r"(?:"
    r"^\d{1,4}(?:号|#)?(?:补)?(?:鉴定意见书|判决书|裁定书|调解书|起诉状|申请书|通知书)$"
    r"|^[\u4e00-\u9fa5]{2,16}(?:价鉴|鉴定|评估|审计|检验|检测|勘验)字$"
    r"|^\d{1,4}\s*#\s*[\u4e00-\u9fa5A-Za-z0-9]{1,20}(?:项目|工程|地块)$"
    r")"
)
_CLAUSE_WRAPPED_ORG_RE = re.compile(
    r"(?:一审法院|二审法院|人民法院|上诉人|被上诉人|案外人|原告|被告|第三人|"
    r"答辩人|驳回|起诉|诉请|未厘清|仍然认|如果其|并未|代表|提交|告知|申请|"
    r"发送|原名|被指|认为|主张|银行)"
)
_COMPANY_ROLE_PREFIX_RE = re.compile(
    r"^(?:再审申请人|申请执行人|被申请人|被执行人|被上诉人|上诉人|申请人|"
    r"被告|原告|第三人|案外人|答辩人)[一二三四五六七八九十\d]*[：:、，,\s]*"
)
_COMPANY_LEGAL_SUFFIXES = (
    "有限责任公司",
    "股份有限公司",
    "集团有限公司",
    "有限公司",
    "公司",
    "集团",
)
_SHORT_ORG_TAIL_SEPARATORS = ("发送", "通知", "告知", "提交", "出具", "系", "为", "以", "代表", "转账至", "汇款至", "支付至")
_BANK_OR_FIRM_SUFFIXES = ("银行", "分行", "支行", "律所")
_PROJECT_SUFFIXES = (
    "风电场",
    "小区",
    "花园",
    "华府",
    "澜庭",
    "蓝庭",
    "公寓",
    "广场",

    "大厦",
    "产业园",
    "商业综合体",
    "小镇",
    "标段",
    "项目",
    "工程",
)

_DOCUMENT_SHAPED_PROJECT_RE = re.compile(
    r"^\d{1,4}\s*#\s*[\u4e00-\u9fa5A-Za-z0-9]{1,20}(?:项目|工程|地块)$"
)
_PROJECT_DOCUMENT_NOISE_RE = re.compile(
    r"(?:合同|清单|报价单|报价|总款|价款|款项|费用|辅料费|采购单|发票|收据)"
)
_GENERIC_PROJECT_RE = re.compile(
    r"^(?:办公大厅|大厅|会议室|机房|楼面|整体|全部|一期|二期|三期|"
    r"[一二三四五六七八九十\d]+期)?"
    r"(?:整体)?(?:装饰|装修|施工|承包|安装|采购|开孔|空调|商厨|改造|维修|"
    r"装潢|水电|消防|弱电|土建|机电|幕墙|门窗|楼面|大厅|会议室|机房)*"
    r"(?:工程|施工|项目)$"
)




def is_noise_entity_text(text: str) -> bool:
    return _is_noise_entity_text(text)


def _is_clause_wrapped_org(text: str) -> bool:
    stripped = text.strip()
    if not any(
        stripped.endswith(suffix)
        for suffix in (*_COMPANY_LEGAL_SUFFIXES, "银行")
    ):
        return False
    if (
        "代表" in stripped
        and not stripped.startswith("法定代表人")
        and not stripped.startswith("诉讼代表人")
    ):
        return True
    if len(stripped) <= 12:
        return False
    return bool(_CLAUSE_WRAPPED_ORG_RE.search(stripped))


def _is_noise_entity_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if _DOCUMENT_OR_PROJECT_COMPANY_NOISE_RE.fullmatch(stripped):
        return True
    if _is_clause_wrapped_org(stripped):
        return True
    if _ORG_ACTION_CLAUSE_RE.search(stripped):
        return True
    if _ORG_RELATION_CLAUSE_RE.search(stripped):
        return True
    if _CONTRACT_NOISE_RE.fullmatch(stripped):
        return True
    if _CONTRACT_NOISE_RE.search(stripped):
        remainder = _CONTRACT_NOISE_RE.sub("", stripped)
        remainder = re.sub(r"[\s，,、；;：:的之与和及]", "", remainder)
        if len(remainder) <= 4:
            return True
    if _FALSE_ORG_CLAUSE_RE.fullmatch(stripped):
        return True
    return False


def is_noise_project_text(text: str) -> bool:
    stripped = text.strip(" ：:，,。；;\n\t")
    if not stripped:
        return True
    if len(stripped) < 3:
        return True
    if _PROJECT_DOCUMENT_NOISE_RE.search(stripped):
        return True
    if not stripped.endswith(_PROJECT_SUFFIXES):
        return True
    if _DOCUMENT_SHAPED_PROJECT_RE.fullmatch(stripped):
        return True
    if stripped in {"建设工程", "工程", "项目", "施工工程", "装修工程", "装饰工程", "安装工程", "整体工程"}:
        return True
    if _GENERIC_PROJECT_RE.fullmatch(stripped):
        return True
    return False





_ENTITY_BOUNDARY_WRAPPERS = " \t\r\n：:，,。；;、\"'“”‘’（）()[]【】"


def _normalize_company_variant(text: str) -> str:
    """Remove only punctuation wrapping an LLM-proposed company surface.

    Balanced parentheses inside an organization name are preserved because they
    may be part of its registered surface, e.g. ``中建二局（集团）有限公司``.
    """
    return text.strip(_ENTITY_BOUNDARY_WRAPPERS)


_LLM_ORG_NARRATIVE_PREFIX_RE = re.compile(r"^(?:所属|按照|根据|由|与|和|及|对|向)")

_LLM_ORG_CLAUSE_PREFIX_RE = re.compile(r"^(?:本院委托|案涉工程续建由)")


def _extract_complete_company_tail(text: str) -> str:
    """Return the last complete organization surface in a model-proposed span."""
    from .filters import clean_organization_text
    from .lexicon import ORG_FULL_RE

    candidates: list[str] = []
    for fragment in (text, *re.split(r"[（(]", text)):
        for match in ORG_FULL_RE.finditer(fragment):
            value = clean_organization_text(match.group(0))
            if value:
                candidates.append(value)
    return candidates[-1] if candidates else ""


def _normalize_llm_company_surface(text: str) -> str:
    """Extract a precise organization surface from an LLM-proposed span."""
    stripped = _normalize_company_variant(text)
    stripped = _LLM_ORG_NARRATIVE_PREFIX_RE.sub("", stripped).strip()
    stripped = _LLM_ORG_CLAUSE_PREFIX_RE.sub("", stripped).strip()
    tail = _extract_complete_company_tail(stripped)
    return tail or stripped


_GENERIC_ORGANIZATION_SURFACES = frozenset({"本工程", "本项目", "该工程", "该项目"})


def _is_valid_org_capture(name: str) -> bool:
    if any(
        noise in name
        for noise in ("以下简称", "下称", "简称", "原名称", "曾用名", "否认其", "合同")
    ):
        return False
    return len(name) >= 4


def _is_valid_company_variant(text: str) -> bool:
    stripped = text.strip()
    if not stripped or stripped != _normalize_company_variant(stripped):
        return False
    if _is_noise_entity_text(stripped):
        return False
    if _COMPANY_ROLE_PREFIX_RE.match(stripped):
        return False
    if stripped in _GENERIC_ORGANIZATION_SURFACES:
        return False
    if _LLM_ORG_CLAUSE_PREFIX_RE.match(stripped):
        return False
    if _INVALID_COMPANY_VARIANT_RE.search(stripped):
        return False

    from .lexicon import ORG_FULL_RE

    match = ORG_FULL_RE.search(stripped)
    if match and match.group(0) == stripped:
        return _is_valid_org_capture(stripped)

    if any(stripped.endswith(suffix) for suffix in _COMPANY_LEGAL_SUFFIXES):
        if "（" in stripped or "(" in stripped:
            return _is_valid_org_capture(stripped)
        return len(stripped) <= 10
    if any(stripped.endswith(suffix) for suffix in _BANK_OR_FIRM_SUFFIXES):
        return len(stripped) <= 12
    return 2 <= len(stripped) <= 8




@dataclass(frozen=True)
class ModelCallMetadata:
    call_count: int = 0
    retry_count: int = 0
    duration_ms: int = 0
    prompt_token_count: int | None = None
    completion_token_count: int | None = None
    total_token_count: int | None = None
    http_status: int | None = None
    finish_reason: str | None = None


@dataclass(frozen=True)
class ModelManagerCallResult:
    response_text: str
    metadata: ModelCallMetadata


@dataclass(frozen=True)
class FullDocumentRegistryExtraction:
    validation: RegistryValidationResult = dataclass_field(default_factory=RegistryValidationResult)
    status: str = "success"
    reason: str | None = None
    metadata: ModelCallMetadata = dataclass_field(default_factory=ModelCallMetadata)

@dataclass
class LegalEntityAuditor:
    config: LLMAPIConfig

    def extract_full_document_registry(
        self,
        text: str,
        enable_samples: bool = False,
    ) -> FullDocumentRegistryExtraction:
        """Extract and validate one document-level entity registry."""
        _ = enable_samples
        if not self.config.enabled:
            _logger.warning("全文 LLM 未执行：原因=llm_disabled。")
            return FullDocumentRegistryExtraction(status="disabled", reason="llm_disabled")
        if len(text) > self.config.full_document_max_chars:
            _logger.warning(
                "全文 LLM 未执行：字符数=%d，限制=%d，原因=input_too_large。",
                len(text),
                self.config.full_document_max_chars,
            )
            return FullDocumentRegistryExtraction(status="fallback", reason="input_too_large")

        primary_prompt = self._build_full_document_registry_prompt(text, enable_samples=False)
        repair_prompt = self._build_registry_repair_prompt(text)
        primary = self._extract_full_document_pass(
            text,
            primary_prompt,
            repair_prompt,
            phase_label="初次登记",
            repair_phase_label="JSON 修复",
        )
        if primary.status != "success":
            return primary

        supplement = self._extract_full_document_pass(
            text,
            self._build_full_document_supplement_prompt(text, primary.validation),
            self._build_full_document_supplement_repair_prompt(text, primary.validation),
            phase_label="二次补漏",
            repair_phase_label="补漏 JSON 修复",
        )
        combined_metadata = self._merge_call_metadata(primary.metadata, supplement.metadata)
        if supplement.status != "success":
            reason = supplement.reason or "unknown"
            _logger.warning(
                "全文 LLM 二次补漏失败：原因=%s；已阻止生成部分脱敏结果。",
                reason,
            )
            return FullDocumentRegistryExtraction(
                status="fallback",
                reason=f"supplement_{reason}",
                metadata=combined_metadata,
            )

        merged = merge_full_document_registries(text, primary.validation, supplement.validation)
        if not merged.valid:
            reason = merged.error or "invalid_registry_payload"
            _logger.warning(
                "全文 LLM 补漏合并失败：原因=%s；已阻止生成部分脱敏结果。",
                reason,
            )
            return FullDocumentRegistryExtraction(
                status="fallback",
                reason=f"supplement_merge_{reason}",
                metadata=combined_metadata,
            )
        _logger.info(
            "全文 LLM 完成：实体=%d，冲突=%d，总调用=%d，总用时=%.2fs。",
            len(merged.registry.entities),
            len(merged.conflicts),
            combined_metadata.call_count,
            combined_metadata.duration_ms / 1000,
        )
        return FullDocumentRegistryExtraction(
            validation=merged,
            status="success",
            metadata=combined_metadata,
        )

    def _extract_full_document_pass(
        self,
        text: str,
        prompt: str,
        repair_prompt: str,
        *,
        phase_label: str,
        repair_phase_label: str,
    ) -> FullDocumentRegistryExtraction:
        attempts = 1 + self.config.full_document_retry_count
        total_metadata = ModelCallMetadata()
        last_reason = "invalid_registry_payload"
        _logger.info(
            "全文 LLM 开始：模型=%s，字符数=%d，最大输出=%d tokens，超时=%ds，最多调用=%d。",
            self.config.model,
            len(text),
            self.config.full_document_max_output_tokens,
            self.config.full_document_timeout_seconds,
            attempts,
        )
        for attempt in range(attempts):
            attempt_number = attempt + 1
            phase = phase_label if attempt == 0 else repair_phase_label
            current_prompt = prompt if attempt == 0 else repair_prompt
            _logger.info("全文 LLM 调用 %d/%d：阶段=%s。", attempt_number, attempts, phase)
            attempt_started = time.monotonic()
            try:
                response = self._call_model_manager_with_metadata(
                    current_prompt,
                    max_tokens=self.config.full_document_max_output_tokens,
                    timeout_seconds=self.config.full_document_timeout_seconds,
                    stop="}",
                )
            except Exception as exc:
                attempt_duration_ms = max(0, int(round((time.monotonic() - attempt_started) * 1000)))
                reason = self._safe_exception_reason(exc)
                http_status = self._exception_http_status(exc)
                total_metadata = self._merge_call_metadata(
                    total_metadata,
                    ModelCallMetadata(
                        call_count=1,
                        retry_count=1 if attempt else 0,
                        duration_ms=attempt_duration_ms,
                        http_status=http_status,
                    ),
                )
                _logger.warning(
                    "全文 LLM 调用 %d/%d 失败：阶段=%s，原因=%s，HTTP=%s，用时=%.2fs；重试耗尽将阻止脱敏。",
                    attempt_number,
                    attempts,
                    phase,
                    reason,
                    http_status if http_status is not None else "无",
                    attempt_duration_ms / 1000,
                )
                return FullDocumentRegistryExtraction(
                    status="fallback",
                    reason=reason,
                    metadata=total_metadata,
                )

            total_metadata = self._merge_call_metadata(
                total_metadata,
                ModelCallMetadata(
                    call_count=response.metadata.call_count,
                    retry_count=1 if attempt else 0,
                    duration_ms=response.metadata.duration_ms,
                    prompt_token_count=response.metadata.prompt_token_count,
                    completion_token_count=response.metadata.completion_token_count,
                    total_token_count=response.metadata.total_token_count,
                    http_status=response.metadata.http_status,
                    finish_reason=response.metadata.finish_reason,
                ),
            )
            _logger.info(
                "全文 LLM 调用 %d/%d 返回：阶段=%s，HTTP=%s，用时=%.2fs，输出 tokens=%s，结束原因=%s。",
                attempt_number,
                attempts,
                phase,
                response.metadata.http_status if response.metadata.http_status is not None else "无",
                response.metadata.duration_ms / 1000,
                response.metadata.completion_token_count if response.metadata.completion_token_count is not None else "未知",
                response.metadata.finish_reason or "未知",
            )
            if response.metadata.finish_reason == "length":
                _logger.warning(
                    "全文 LLM 输出达到 token 上限；判定为输出失控并停止，不执行同参数重试。"
                )
                return FullDocumentRegistryExtraction(
                    status="fallback",
                    reason="output_token_limit",
                    metadata=total_metadata,
                )
            repaired_payload = self._repair_full_document_registry_payload(response.response_text)
            parsed = parse_full_document_registry(repaired_payload or response.response_text)
            if not parsed.valid:
                last_reason = parsed.error or "invalid_registry_payload"
                if attempt + 1 < attempts:
                    _logger.warning(
                        "全文 LLM 输出校验失败：调用=%d/%d，原因=%s；将执行 JSON 修复重试。",
                        attempt_number,
                        attempts,
                        last_reason,
                    )
                    continue
                _logger.warning(
                    "全文 LLM 输出校验失败：调用=%d/%d，原因=%s；重试耗尽将阻止脱敏。",
                    attempt_number,
                    attempts,
                    last_reason,
                )
                return FullDocumentRegistryExtraction(
                    validation=parsed,
                    status="fallback",
                    reason=last_reason,
                    metadata=total_metadata,
                )
            validated = validate_registry_against_text(text, parsed)
            if not validated.valid:
                reason = validated.error or "invalid_registry_payload"
                _logger.warning(
                    "全文 LLM 文本一致性校验失败：原因=%s；已阻止脱敏。",
                    reason,
                )
                return FullDocumentRegistryExtraction(
                    validation=validated,
                    status="fallback",
                    reason=reason,
                    metadata=total_metadata,
                )
            _logger.info(
                "全文 LLM 阶段成功：阶段=%s，实体=%d，冲突=%d，调用=%d，用时=%.2fs。",
                phase_label,
                len(validated.registry.entities),
                len(validated.conflicts),
                total_metadata.call_count,
                total_metadata.duration_ms / 1000,
            )
            return FullDocumentRegistryExtraction(
                validation=validated,
                status="success",
                metadata=total_metadata,
            )
        return FullDocumentRegistryExtraction(status="fallback", reason=last_reason, metadata=total_metadata)



    def _call_model_manager(self, prompt: str, *, max_tokens: int = _AUDIT_MAX_TOKENS) -> dict:
        """Compatibility wrapper for direct transport tests and diagnostics."""
        response = self._call_model_manager_with_metadata(prompt, max_tokens=max_tokens)
        try:
            payload = json.loads(response.response_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Model manager returned invalid completion JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Model manager returned a non-object completion")
        return payload

    def _call_model_manager_with_metadata(
        self,
        prompt: str,
        *,
        max_tokens: int = _AUDIT_MAX_TOKENS,
        timeout_seconds: int | None = None,
        stop: str | None = None,
    ) -> ModelManagerCallResult:
        body = json.dumps(
            {
                "model": self.config.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "temperature": self.config.temperature,
                "max_tokens": max_tokens,
                "chat_template_kwargs": {"enable_thinking": False},
                **({"stop": stop} if stop is not None else {}),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        connection = http.client.HTTPConnection(
            self.config.model_manager_host,
            self.config.model_manager_port,
            timeout=timeout_seconds or self.config.timeout_seconds,
        )
        started = time.monotonic()
        status: int | None = None
        try:
            connection.request(
                "POST",
                "/v1/chat/completions",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            status = response.status
            data = response.read().decode("utf-8", errors="replace")
        finally:
            connection.close()
        duration_ms = max(0, int(round((time.monotonic() - started) * 1000)))

        if status is not None and status >= 400:
            raise RuntimeError(f"Model manager HTTP {status}")

        try:
            raw = json.loads(data)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Model manager returned invalid JSON") from exc
        choices = raw.get("choices", []) if isinstance(raw, dict) else []
        if not choices:
            raise RuntimeError("Model manager returned an empty response")
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        response_text = message.get("content", "") if isinstance(message, dict) else ""
        finish_reason = choices[0].get("finish_reason") if isinstance(choices[0], dict) else None
        usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
        return ModelManagerCallResult(
            response_text=response_text if isinstance(response_text, str) else "",
            metadata=ModelCallMetadata(
                call_count=1,
                duration_ms=duration_ms,
                prompt_token_count=self._usage_int(usage, "prompt_tokens"),
                completion_token_count=self._usage_int(usage, "completion_tokens"),
                total_token_count=self._usage_int(usage, "total_tokens"),
                http_status=status,
                finish_reason=finish_reason if isinstance(finish_reason, str) else None,
            ),
        )

    @classmethod
    def _repair_full_document_registry_payload(cls, value: str) -> str | None:
        """Close a max-token-truncated registry without inventing entity text."""
        if cls._json_decode_failure_kind(value) != "truncated":
            return None
        repaired = cls._repair_json_text(value)
        try:
            parsed = json.loads(repaired)
        except JSONDecodeError:
            return None
        return repaired if isinstance(parsed, dict) else None

    @staticmethod
    def _json_decode_failure_kind(value: str) -> str:
        """Classify a failed JSON payload shape without echoing document text."""
        text = value.strip()
        if not text:
            return "invalid"
        if text.startswith("```"):
            text = text.strip("`")
            text = text.replace("json\n", "", 1).replace("JSON\n", "", 1).strip()
        start = text.find("{")
        if start < 0:
            return "invalid"
        fragment = text[start:]
        stack: list[str] = []
        in_string = False
        escape = False
        for char in fragment:
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                stack.append("}")
            elif char == "[":
                stack.append("]")
            elif char in "}]" and stack and stack[-1] == char:
                stack.pop()
        if in_string or stack or fragment.rstrip().endswith((",", ":", "[", "{")):
            return "truncated"
        return "invalid"

    @staticmethod
    def _repair_json_text(value: str) -> str:
        """Best-effort repair for max_tokens-truncated model JSON.

        Closes open strings with content, drops incomplete trailing keys/values,
        then closes any remaining containers. Never invents entity text beyond
        characters already present in the model output.
        """
        text = value.rstrip()
        if not text:
            return text

        n = len(text)
        stack: list[str] = []
        in_string = False
        escape = False
        string_is_value = False
        expecting_value = False
        last_safe = 0
        i = 0
        while i < n:
            char = text[i]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                    if string_is_value:
                        expecting_value = False
                        last_safe = i + 1
                i += 1
                continue
            if char.isspace():
                i += 1
                continue
            if char == '"':
                in_string = True
                if stack and stack[-1] == "]":
                    string_is_value = True
                else:
                    string_is_value = expecting_value
                i += 1
                continue
            if char in "tfn":
                matched = False
                for literal in ("true", "false", "null"):
                    if text.startswith(literal, i):
                        i += len(literal)
                        expecting_value = False
                        last_safe = i
                        matched = True
                        break
                if not matched:
                    i += 1
                continue
            if char == "-" or char.isdigit():
                j = i + 1
                while j < n and (text[j].isdigit() or text[j] in ".eE+-"):
                    j += 1
                i = j
                expecting_value = False
                last_safe = i
                continue
            if char == "{":
                stack.append("}")
                expecting_value = False
                i += 1
                continue
            if char == "[":
                stack.append("]")
                expecting_value = True
                i += 1
                continue
            if char == "}":
                if stack and stack[-1] == "}":
                    stack.pop()
                    expecting_value = False
                    last_safe = i + 1
                i += 1
                continue
            if char == "]":
                if stack and stack[-1] == "]":
                    stack.pop()
                    expecting_value = False
                    last_safe = i + 1
                i += 1
                continue
            if char == ":":
                expecting_value = True
                i += 1
                continue
            if char == ",":
                expecting_value = bool(stack and stack[-1] == "]")
                i += 1
                continue
            i += 1

        if in_string and string_is_value:
            # The last entity value is incomplete. Keep only the last complete
            # JSON value; accepting a clipped name would create a false entity.
            prefix = text[:last_safe].rstrip()
            while prefix.endswith(","):
                prefix = prefix[:-1].rstrip()
        else:
            if not in_string and not expecting_value and not stack:
                prefix = text
            else:
                prefix = text[:last_safe].rstrip()
            while prefix.endswith(","):
                prefix = prefix[:-1].rstrip()
            if prefix.endswith(":"):
                stripped = prefix[:-1].rstrip()
                if stripped.endswith('"'):
                    key_end = len(stripped) - 1
                    key_start = key_end - 1
                    while key_start >= 0:
                        if stripped[key_start] == '"':
                            backslashes = 0
                            cursor = key_start - 1
                            while cursor >= 0 and stripped[cursor] == "\\":
                                backslashes += 1
                                cursor -= 1
                            if backslashes % 2 == 0:
                                stripped = stripped[:key_start].rstrip()
                                if stripped.endswith(","):
                                    stripped = stripped[:-1].rstrip()
                                break
                        key_start -= 1
                prefix = stripped

        stack = []
        in_string = False
        escape = False
        for char in prefix:
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                stack.append("}")
            elif char == "[":
                stack.append("]")
            elif char in "}]" and stack and stack[-1] == char:
                stack.pop()
        if in_string:
            prefix += '"'
        return prefix + "".join(reversed(stack))



    @staticmethod
    def _usage_int(usage: object, key: str) -> int | None:
        if not isinstance(usage, dict):
            return None
        value = usage.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    @staticmethod
    def _merge_call_metadata(left: ModelCallMetadata, right: ModelCallMetadata) -> ModelCallMetadata:
        def add_optional(a: int | None, b: int | None) -> int | None:
            if a is None and b is None:
                return None
            return (a or 0) + (b or 0)

        return ModelCallMetadata(
            call_count=left.call_count + right.call_count,
            retry_count=left.retry_count + right.retry_count,
            duration_ms=left.duration_ms + right.duration_ms,
            prompt_token_count=add_optional(left.prompt_token_count, right.prompt_token_count),
            completion_token_count=add_optional(left.completion_token_count, right.completion_token_count),
            total_token_count=add_optional(left.total_token_count, right.total_token_count),
            finish_reason=right.finish_reason if right.finish_reason is not None else left.finish_reason,
            http_status=right.http_status if right.http_status is not None else left.http_status,
        )

    @staticmethod
    def _safe_exception_reason(exc: Exception) -> str:
        if isinstance(exc, TimeoutError):
            return "timeout"
        match = re.search(r"HTTP (\d{3})", str(exc))
        if match:
            return f"http_{match.group(1)}"
        return type(exc).__name__.lower()

    @staticmethod
    def _exception_http_status(exc: Exception) -> int | None:
        match = re.search(r"HTTP (\d{3})", str(exc))
        return int(match.group(1)) if match else None

    def _build_registry_repair_prompt(self, text: str) -> str:
        return (
            "/no_think\n"
            "上一轮输出不是合法的案件级实体 JSON。重新阅读同一全文，只输出一行紧凑 JSON；"
            "顶层必须且只能有 persons、organizations、locations、same_entities 四个数组。"
            "前三个数组只列去重后的原文实体名称；same_entities 只列原文用又名、曾用名、简称、以下简称或同一人明确确认的两个不同名称。"
            "same_entities 两项文字必须不同，禁止名称与自身配对；不同诉讼角色、同段出现、姓名相似或模型推断都不构成同一主体；张三与李四这类不同完整人名禁止合并。"
            "不要证据、解释、Markdown、换行或其他字段。输出最后一个 } 后立即停止。\n"
            "格式：{\"persons\":[\"张三\"],\"organizations\":[\"星河建设有限公司\",\"星河公司\"],"
            "\"locations\":[\"北京市\"],\"same_entities\":[[\"星河建设有限公司\",\"星河公司\"]]}\n"
            f"=== 文书全文 ===\n{text}\n"
        )

    def _build_full_document_registry_prompt(
        self,
        text: str,
        enable_samples: bool = False,
    ) -> str:
        _ = enable_samples
        return (
            "/no_think\n"
            "你是法律文书案件级实体登记器。阅读完整文书后，只输出一行紧凑 JSON。"
            "顶层必须且只能有 persons、organizations、locations、same_entities 四个数组。"
            "persons、organizations、locations 只列去重后的原文名称字符串；每个名称只出现一次。"
            "same_entities 只列原文用又名、曾用名、简称、以下简称或同一人明确确认的同一主体两个不同名称；无法确认就不列。"
            "same_entities 两项文字必须不同，禁止名称与自身配对；不同诉讼角色、同段出现、姓名相似或模型推断都不构成同一主体；张三与李四这类不同完整人名禁止合并。"
            "名称必须逐字来自原文，不得改写、补空格或规范化数字。"
            "只登记 person、organization、location；禁止登记普通指代、职务称谓、审判人员、法官助理、书记员、"
            "项目、合同、案号、电话、身份证号、银行账号、详细地址或其他编号。"
            "地点只登记符合当前脱敏策略的行政区划名称。没有某类实体或映射时使用空数组。"
            "不要证据、entity_id、type、confidence、解释、Markdown、脱敏稿、换行或其他字段。"
            "输出最后一个 } 后立即停止。\n"
            "输出格式："
            '{"persons":["张三","李四"],'
            '"organizations":["星河建设有限公司","星河公司"],'
            '"locations":["北京市"],'
            '"same_entities":[["星河建设有限公司","星河公司"]]}\n'
            f"=== 文书全文 ===\n{text}\n"
        )

    def _build_full_document_supplement_prompt(
        self,
        text: str,
        primary: RegistryValidationResult,
    ) -> str:
        known = {
            "persons": [],
            "organizations": [],
            "locations": [],
        }
        for entity in primary.registry.entities:
            key = {
                "person": "persons",
                "organization": "organizations",
                "location": "locations",
            }.get(entity.entity_type)
            if key is not None:
                known[key].extend(entity.variants)
        known_json = json.dumps(known, ensure_ascii=False, separators=(",", ":"))
        return (
            "/no_think\n"
            "你是法律文书案件级实体补漏器。重新阅读完整文书，只列第一轮遗漏的 person、organization、location 原文名称，"
            "以及遗漏名称与已登记名称之间明确的同一主体映射。只输出一个紧凑 JSON 对象；"
            "顶层必须且只能有 persons、organizations、locations、same_entities 四个数组，每个字段只允许出现一次。"
            "严禁输出第一轮已有名称。没有遗漏时，必须逐字输出"
            '{"persons":[],"organizations":[],"locations":[],"same_entities":[]}。'
            "名称必须逐字来自原文。"
            "禁止登记普通指代、职务称谓、审判人员、法官助理、书记员、项目、合同、案号、电话、身份证号、银行账号、"
            "详细地址或其他编号。地点只登记符合当前脱敏策略的行政区划名称。"
            "same_entities 每项必须恰好包含两个不同名称，禁止名称与自身配对，且原文必须用又名、曾用名、简称、以下简称或同一人明确确认其为同一主体。"
            "不同诉讼角色、同段出现、姓名相似或模型推断都不构成同一主体；不同完整人名禁止合并。"
            "不要重复字段、重复对象、证据、解释、Markdown、换行或其他字段。输出第一个完整对象后立即停止。\n"
            f"=== 第一轮已登记名称（禁止再次输出）===\n{known_json}\n"
            f"=== 文书全文 ===\n{text}\n"
        )
    def _build_full_document_supplement_repair_prompt(
        self,
        text: str,
        primary: RegistryValidationResult,
    ) -> str:
        return (
            "上一轮补漏输出不是合法 JSON。重新执行同一个补漏任务，并严格使用以下格式。\n"
            + self._build_full_document_supplement_prompt(text, primary)
        )
