from __future__ import annotations

import http.client
import json
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any

from .config import LocalLLMConfig


def get_context_paragraphs(text: str, max_chars: int = 8000) -> str:
    """通过段落/行对齐提取上下文，防止中途断句、断词，自适应处理 OCR 换行。"""
    if len(text) <= max_chars:
        return text

    lines = text.splitlines(keepends=True)
    current_chars = 0
    selected_lines = []

    for line in lines:
        if current_chars + len(line) > max_chars:
            # 只有在已经收集了内容的情况下才提前中断，确保不为空
            if selected_lines:
                break
        selected_lines.append(line)
        current_chars += len(line)

    return "".join(selected_lines)


@dataclass
class LegalEntityAuditor:
    config: LocalLLMConfig

    def audit_and_verify(self, text: str, candidates: list[dict], enable_samples: bool = True) -> dict[str, Any]:
        """合并审计提取与疑似候选词验证，单次调用 LLM。

        Args:
            text: 原文
            candidates: 待验证的正则/启发式候选列表，每项含 {"text", "type", "context"}
            enable_samples: 是否注入历史样本作为 few-shot
        """
        if not self.config.enabled:
            return {"locations": [], "companies": [], "persons": [], "reject": []}

        # 段落对齐切片，提取高质量上下文
        audit_text = get_context_paragraphs(text, max_chars=8000)
        prompt = self._build_merged_prompt(audit_text, candidates, enable_samples=enable_samples)

        try:
            payload = self._call_ollama(prompt)
            return payload
        except Exception as exc:
            import sys
            print(f"\n[legal-redactor] 语义审计与验证联合调用失败：{exc}", file=sys.stderr)
            # 联合调用失败时，返回空提取，并采用 fail-open（空拒绝列表）以保留所有规则候选
            return {"locations": [], "companies": [], "persons": [], "reject": [], "error": str(exc)}

    def _call_ollama(self, prompt: str) -> dict[str, Any]:
        models = []
        if self.config.model:
            models.append(self.config.model)
        for m in self.config.fallback_models:
            if m not in models:
                models.append(m)

        errors = []
        for model in models:
            try:
                return self._call_ollama_model(prompt, model)
            except Exception as e:
                errors.append(f"{model}: {e}")
        raise RuntimeError("LLM 调用失败: " + "; ".join(errors))

    def _call_ollama_model(self, prompt: str, model: str) -> dict[str, Any]:
        body = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "keep_alive": "1m",
                "options": {
                    "temperature": self.config.temperature,
                    "num_ctx": self.config.context_window,
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")
        conn = http.client.HTTPConnection(
            self.config.ollama_host,
            self.config.ollama_port,
            timeout=self.config.timeout_seconds,
        )
        try:
            conn.request(
                "POST",
                "/api/generate",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            data = response.read().decode("utf-8", errors="replace")
        finally:
            conn.close()

        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status}: {data[:200]}")

        raw = json.loads(data)
        response_text = raw.get("response", "") or raw.get("thinking", "")
        return self._parse_json(response_text)

    def _parse_json(self, value: str) -> dict[str, Any]:
        value = value.strip()
        if value.startswith("```"):
            value = value.strip("`")
            value = value.replace("json\n", "", 1).replace("JSON\n", "", 1)
        start = value.find("{")
        end = value.rfind("}")
        if start >= 0 and end >= start:
            value = value[start : end + 1]
        try:
            data = json.loads(value)
            if not isinstance(data, dict):
                data = {}
            for key in ("locations", "companies", "persons"):
                items = data.get(key, [])
                data[key] = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
            reject = data.get("reject", [])
            data["reject"] = [item for item in reject if isinstance(item, str)] if isinstance(reject, list) else []
            calibrate = data.get("calibrate", {})
            data["calibrate"] = {
                key: item
                for key, item in calibrate.items()
                if isinstance(key, str) and isinstance(item, str)
            } if isinstance(calibrate, dict) else {}
            return data
        except JSONDecodeError:
            return {"locations": [], "companies": [], "persons": [], "reject": [], "calibrate": {}, "error": "JSON decode failed"}

    def _build_merged_prompt(self, text: str, candidates: list[dict], enable_samples: bool = True) -> str:
        from ._samples import get_few_shot_examples
        few_shot_str = get_few_shot_examples() if enable_samples else ""
        few_shot_part = f"\n{few_shot_str}\n\n" if few_shot_str else ""

        candidate_lines = []
        for i, c in enumerate(candidates, 1):
            ctx = c.get("context", "")
            candidate_lines.append(
                f'{i}. 类型={c["type"]}, 文本=「{c["text"]}」, 上下文=「...{ctx}...」'
            )
        candidates_str = "\n".join(candidate_lines) if candidate_lines else "暂无需要校验的候选词"

        return (
            "你是一个资深的法律文书脱敏专家与质量审核员。请分析以下法律文书，并对疑似实体进行过滤校验。\n\n"
            f"{few_shot_part}"
            "## 任务 1：提取真实存在的实体【原子词】\n"
            "你需要从文书的【文书原文（部分）】中提取出所有的地名、公司/机构名、以及自然人姓名，并将其拆解为【原子词】。\n"
            "核心目标是提取：地名的核心词（不含省市区后缀）、公司机构的品牌字号（不含业务描述和公司后缀）、人的姓氏。\n"
            "只提取真实出现且需要脱敏的实体，不要提取泛称（如“原告”、“被告”、“本院”）。\n\n"
            "## 任务 2：校验疑似实体候选列表（过滤误匹配）\n"
            "下面是脱敏系统通过正则/启发式规则匹配到的【候选列表】。请你逐一审核，将其中【明显的误识别】放入 reject 数组。\n"
            "判断标准：\n"
            "- 应该【保留】（不要放入 reject）：真实的省市区县地名、真实存在的公司/机构名/律所、公司简称、真实的人名。\n"
            "- 应该【剔除】（放入 reject）：包含“公司”但不是公司名的普通表述（如：来我去公司、如果你们公司、严重阻碍我公司、导致公司办公区）、"
            "非行政区划的类似表述（如：合理区、办公区、广场东区）、完整公司名的残余子串、无品牌名的纯法律后缀（如：有限责任公司、家具有限公司）、"
            "明显不是人名的短语（如：一审法院、请求已无、合同无效、配合协助等）。\n\n"
            "## 任务 3：候选实体边界校准与切片净化（非必填）\n"
            "如果【候选列表】中的某些项目包含真实的实体，但在提取或匹配切片时出现了以下问题，请在 JSON 的 `calibrate` 字典中以 `\"候选词\": \"校准后的正确纯净实体\"` 的键值对进行输出：\n"
            "1. **前缀/后缀混入杂质**：夹带多余动作词、连词、介词或人名。例如「某人无权代表星河公司」应校准为「星河公司」。示例名称均为虚构。\n"
            "2. **前导括号/标点残留**：例如「）示例省星河药业有限公司」应校准为「示例省星河药业有限公司」。\n"
            "3. **严重切片或截断**：结合原文恢复完整实体，但校准结果必须逐字存在于原文中。\n"
            "如果候选词已经很纯净或完全不需保留，不要放入 `calibrate`，而是应该放入 `reject`。\n\n"
            "## 输出格式\n"
            "输出必须为严格的 JSON 格式，且包含 locations, companies, persons, reject 四个数组，以及可选的 calibrate 字典：\n"
            "{\n"
            '  "locations": [\n'
            '    {"full": "示例省", "core": "示例", "suffix": "省"},\n'
            '    {"full": "样例市", "core": "样例", "suffix": "市"}\n'
            '  ],\n'
            '  "companies": [\n'
            '    {"brand": "星河", "variants": ["星河科技有限责任公司", "星河公司"]}\n'
            '  ],\n'
            '  "persons": [\n'
            '    {"name": "林甲明", "surname": "林"}\n'
            '  ],\n'
            '  "reject": ["来我去公司", "办公区"],\n'
            '  "calibrate": {\n'
            '    "某人无权代表星河公司": "星河公司",\n'
            '    "）示例省星河药业有限公司": "示例省星河药业有限公司"\n'
            '  }\n'
            "}\n\n"
            "注意：\n"
            "1. companies 中的 brand（品牌字号）必须精准。例如虚构名称“星河科技有限责任公司”的品牌词是“星河”，不能包含行业词“科技”。\n"
            "2. 宁可漏掉误识别，也不要错误剔除原文中上下文明确的地名、人名或机构名。\n\n"
            f"=== 候选列表 ===\n{candidates_str}\n\n"
            f"=== 文书原文（部分）===\n{text}\n"
        )
