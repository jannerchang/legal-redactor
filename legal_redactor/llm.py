from __future__ import annotations

import http.client
import json
import re
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


def build_sentence_windows(text: str, max_chars: int = 6000, max_windows: int = 40) -> list[dict[str, str]]:
    """Split text into target sentence windows with previous/next context."""
    spans: list[tuple[str, int, int]] = []
    pattern = re.compile(r"[^\n。！？；;]+[。！？；;]?|[^\n]+")
    for match in pattern.finditer(text):
        sentence = match.group(0).strip()
        if not sentence:
            continue
        spans.append((sentence, match.start(), match.end()))
        if len(spans) >= max_windows:
            break
        if match.end() >= max_chars:
            break

    windows: list[dict[str, str]] = []
    for index, (sentence, start, end) in enumerate(spans):
        previous = spans[index - 1][0] if index > 0 else ""
        following = spans[index + 1][0] if index + 1 < len(spans) else ""
        windows.append(
            {
                "id": f"s{index + 1}",
                "previous": previous,
                "target": sentence,
                "next": following,
                "start": str(start),
                "end": str(end),
            }
        )
    return windows


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

        # Candidate review only needs nearby evidence, not a full-document extraction.
        audit_text = get_context_paragraphs(text, max_chars=4000)
        prompt = self._build_merged_prompt(audit_text, candidates, enable_samples=enable_samples)

        try:
            payload = self._call_local_model(prompt)
            return self._normalize_candidate_review_payload(payload, candidates)
        except Exception as exc:
            import sys
            print(f"\n[legal-redactor] 语义审计与验证联合调用失败：{exc}", file=sys.stderr)
            # 联合调用失败时，返回空提取，并采用 fail-open（空拒绝列表）以保留所有规则候选
            return {"locations": [], "companies": [], "persons": [], "reject": [], "error": str(exc)}

    def extract_sentence_entities(self, text: str, enable_samples: bool = True) -> dict[str, Any]:
        """Extract entities from sentence windows; context is previous/next sentence only."""
        if not self.config.enabled:
            return {"locations": [], "companies": [], "persons": [], "projects": [], "reject": [], "calibrate": {}}

        if self.config.mode == "balanced":
            windows = build_sentence_windows(text, max_chars=4500, max_windows=24)
        else:
            windows = build_sentence_windows(text)
        if not windows:
            return {"locations": [], "companies": [], "persons": [], "projects": [], "reject": [], "calibrate": {}}

        prompt = self._build_sentence_extraction_prompt(windows, enable_samples=enable_samples)
        try:
            payload = self._call_local_model(prompt)
            payload["_sentence_windows"] = windows
            return payload
        except Exception as exc:
            import sys
            print(f"\n[legal-redactor] 整句语义识别调用失败：{exc}", file=sys.stderr)
            return {
                "locations": [],
                "companies": [],
                "persons": [],
                "projects": [],
                "reject": [],
                "calibrate": {},
                "error": str(exc),
            }

    def _call_local_model(self, prompt: str) -> dict[str, Any]:
        if self.config.backend == "mlx":
            return self._call_mlx(prompt)
        return self._call_ollama(prompt)

    def _call_mlx(self, prompt: str) -> dict[str, Any]:
        return self._call_mlx_model(prompt, self.config.model)

    def _call_mlx_model(self, prompt: str, model: str) -> dict[str, Any]:
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "temperature": self.config.temperature,
                "max_tokens": 4096,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        conn = http.client.HTTPConnection(
            self.config.mlx_host,
            self.config.mlx_port,
            timeout=self.config.timeout_seconds,
        )
        try:
            conn.request(
                "POST",
                "/v1/chat/completions",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            data = response.read().decode("utf-8", errors="replace")
        finally:
            conn.close()

        if response.status >= 400:
            raise RuntimeError(f"MLX HTTP {response.status}: {data[:200]}")

        raw = json.loads(data)
        choices = raw.get("choices", [])
        if not choices:
            raise RuntimeError(f"MLX empty response: {data[:200]}")
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        response_text = message.get("content", "") if isinstance(message, dict) else ""
        return self._parse_json(response_text)

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
                "think": False,
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
            for key in ("locations", "companies", "persons", "projects"):
                items = data.get(key, [])
                data[key] = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
            reject = data.get("reject", [])
            data["reject"] = self._string_list(reject, include_numbers=False) if isinstance(reject, list) else []
            reject_ids = data.get("reject_ids", [])
            data["reject_ids"] = self._string_list(reject_ids, include_numbers=True) if isinstance(reject_ids, list) else []
            calibrate = data.get("calibrate", {})
            data["calibrate"] = {
                key: item
                for key, item in calibrate.items()
                if isinstance(key, str) and isinstance(item, str)
            } if isinstance(calibrate, dict) else {}
            calibrate_ids = data.get("calibrate_ids", {})
            data["calibrate_ids"] = {
                str(key): item
                for key, item in calibrate_ids.items()
                if isinstance(item, str)
            } if isinstance(calibrate_ids, dict) else {}
            return data
        except JSONDecodeError:
            return {"locations": [], "companies": [], "persons": [], "projects": [], "reject": [], "calibrate": {}, "error": "JSON decode failed"}

    @staticmethod
    def _string_list(items: list[Any], *, include_numbers: bool) -> list[str]:
        values: list[str] = []
        for item in items:
            if isinstance(item, str):
                values.append(item)
            elif include_numbers and isinstance(item, (int, float)):
                values.append(str(int(item)) if isinstance(item, float) and item.is_integer() else str(item))
            elif isinstance(item, dict):
                for key in ("candidate", "text", "name", "id"):
                    value = item.get(key)
                    if isinstance(value, str):
                        values.append(value)
                        break
                    if include_numbers and isinstance(value, (int, float)):
                        values.append(str(int(value)) if isinstance(value, float) and value.is_integer() else str(value))
                        break
        return values

    def _normalize_candidate_review_payload(self, payload: dict[str, Any], candidates: list[dict]) -> dict[str, Any]:
        """Map ID-based candidate review output back to the existing text-based contract."""
        id_to_text: dict[str, str] = {}
        candidate_texts: set[str] = set()
        for index, candidate in enumerate(candidates, 1):
            text = candidate.get("text")
            if not isinstance(text, str) or not text:
                continue
            candidate_texts.add(text)
            id_to_text[str(candidate.get("id") or index)] = text

        reject: list[str] = []
        for item in payload.get("reject", []):
            if item in candidate_texts and item not in reject:
                reject.append(item)
            elif item in id_to_text and id_to_text[item] not in reject:
                reject.append(id_to_text[item])
        for item in payload.get("reject_ids", []):
            text = id_to_text.get(str(item))
            if text and text not in reject:
                reject.append(text)

        calibrate: dict[str, str] = {}
        raw_calibrate = payload.get("calibrate", {})
        if isinstance(raw_calibrate, dict):
            for key, value in raw_calibrate.items():
                if not isinstance(value, str):
                    continue
                text_key = id_to_text.get(str(key), key)
                if isinstance(text_key, str) and text_key:
                    calibrate[text_key] = value
        raw_calibrate_ids = payload.get("calibrate_ids", {})
        if isinstance(raw_calibrate_ids, dict):
            for key, value in raw_calibrate_ids.items():
                text_key = id_to_text.get(str(key))
                if text_key and isinstance(value, str):
                    calibrate[text_key] = value

        payload["reject"] = reject
        payload["calibrate"] = calibrate
        return payload

    def _build_sentence_extraction_prompt(self, windows: list[dict[str, str]], enable_samples: bool = True) -> str:
        from ._samples import get_few_shot_examples

        few_shot_str = get_few_shot_examples() if enable_samples else ""
        few_shot_part = f"\n{few_shot_str}\n\n" if few_shot_str else ""
        window_lines: list[str] = []
        for item in windows:
            window_lines.append(
                "窗口 {id}\n上一句：{previous}\n目标句：{target}\n下一句：{next}".format(
                    id=item["id"],
                    previous=item.get("previous", ""),
                    target=item.get("target", ""),
                    next=item.get("next", ""),
                )
            )
        windows_str = "\n\n".join(window_lines)

        return (
            "/no_think\n"
            "你是法律文书脱敏实体识别器。只输出 JSON，不解释、不复述输入。\n"
            "每个窗口包含上一句、目标句、下一句；上一句和下一句只用于理解语义。\n"
            "你只能抽取【目标句】里逐字存在的实体，禁止从上下文句新增实体，禁止改写实体文字。\n\n"
            f"{few_shot_part}"
            "需要抽取的实体类型：\n"
            "- persons: 真实人名，当事人、代理人、证人、负责人等。\n"
            "- companies: 公司、机构、银行、学校、幼儿园、律所、工程局、简称或上下文明确的机构别名。\n"
            "- locations: 省市区县镇乡街道村社区、地址语境中的地名、楼盘/小区/住址地名。\n"
            "- projects: 工程、项目、楼盘、小区、华府、澜庭、蓝庭等项目或楼盘名。\n"
            "不要抽取案号、金额、日期、普通法律术语、动作短语、泛称词。\n\n"
            "输出格式严格如下。每个对象的 text/name/full 必须是目标句原文子串；window 填窗口 id：\n"
            "{\n"
            '  "locations": [{"window": "s1", "full": "示例地名", "core": "示例地名"}],\n'
            '  "companies": [{"window": "s1", "name": "示例公司", "variants": ["示例公司"]}],\n'
            '  "persons": [{"window": "s1", "name": "张三", "surname": "张"}],\n'
            '  "projects": [{"window": "s1", "name": "示例项目"}],\n'
            '  "reject": [],\n'
            '  "calibrate": {}\n'
            "}\n\n"
            "如果不确定，不要输出该实体。宁可少抽取，也不要输出目标句里不存在的文字。\n\n"
            f"=== 句子窗口 ===\n{windows_str}\n"
        )

    def _build_merged_prompt(self, text: str, candidates: list[dict], enable_samples: bool = True) -> str:
        from ._samples import get_few_shot_examples
        few_shot_str = get_few_shot_examples() if enable_samples else ""
        few_shot_part = f"\n{few_shot_str}\n\n" if few_shot_str else ""

        candidate_lines = []
        for i, c in enumerate(candidates, 1):
            ctx = c.get("context", "")
            candidate_lines.append(
                f'ID={i} 类型={c["type"]}, 文本=「{c["text"]}」, 上下文=「...{ctx}...」'
            )
        candidates_str = "\n".join(candidate_lines) if candidate_lines else "暂无需要校验的候选词"

        return (
            "/no_think\n"
            "你是法律文书脱敏候选审核器。只做候选分类，禁止解释任务、禁止复述输入。\n"
            "最终回复只能是一个 JSON 对象，顶层只能有 reject_ids、calibrate_ids 两个键。\n"
            "正确候选不要输出，禁止输出保留理由，禁止输出 companies/persons/locations，禁止输出候选原文列表。\n\n"
            f"{few_shot_part}"
            "## 任务 1：校验疑似实体候选列表\n"
            "下面是脱敏系统通过正则/启发式规则匹配到的【候选列表】。请你逐一审核，将其中【明显的误识别】的 ID 放入 reject_ids 数组。\n"
            "判断标准：\n"
            "- 应该【保留】（不要放入 reject）：真实的省市区县地名、真实存在的公司/机构名/律所、公司简称、真实的人名。\n"
            "- 应该【剔除】（放入 reject_ids）：包含“公司”但不是公司名的普通表述（如：来我去公司、如果你们公司、严重阻碍我公司、导致公司办公区）、"
            "非行政区划的类似表述（如：合理区、办公区、广场东区）、完整公司名的残余子串、无品牌名的纯法律后缀（如：有限责任公司、家具有限公司）、"
            "明显不是人名的短语（如：一审法院、请求已无、合同无效、配合协助等）。\n"
            "- 候选是短片段时要从上下文判断：如果它只是更长公司名、人名、项目名或案号的一部分，必须 reject。"
            "例如「路达」出现在「江苏路达电力工程有限公司」内不是人名；「王文」出现在「王文其」内不是独立人名；"
            "「（2024」是案号/日期片段，不是地名。\n"
            "- 公司简称只有在上下文明确表示公司/机构时才保留，如「大唐公司」「拓欧公司」。"
            "孤立品牌词或被 HanLP 误标成人名/地点的公司字号，应 reject 或校准为上下文中的公司简称。\n\n"
            "## 任务 2：候选实体边界校准（非必填）\n"
            "如果【候选列表】中的某些项目包含真实的实体，但在提取或匹配切片时出现了以下问题，请在 JSON 的 `calibrate_ids` 字典中以 `\"ID\": \"校准后的正确纯净实体\"` 的键值对进行输出：\n"
            "1. **前缀/后缀混入杂质**：夹带多余动作词、连词、介词或人名。例如「某人无权代表星河公司」应校准为「星河公司」。示例名称均为虚构。\n"
            "2. **前导括号/标点残留**：例如「）示例省星河药业有限公司」应校准为「示例省星河药业有限公司」。\n"
            "3. **严重切片或截断**：结合原文恢复完整实体，但校准结果必须逐字存在于原文中。\n"
            "如果候选词已经很纯净或完全不需保留，不要放入 `calibrate_ids`，而是应该放入 `reject_ids`。\n\n"
            "每个候选必须做出处理：正确候选完全不输出；错误候选 ID 放入 reject_ids；"
            "含有真实实体但边界错误的候选 ID 放入 calibrate_ids。不要新增候选列表以外的项目。\n\n"
            "## 输出格式\n"
            "输出严格 JSON。只填写 reject_ids 和可选 calibrate_ids：\n"
            "{\n"
            '  "reject_ids": [2, 5],\n'
            '  "calibrate_ids": {\n'
            '    "3": "星河公司",\n'
            '    "4": "示例省星河药业有限公司"\n'
            '  }\n'
            "}\n\n"
            "例如：候选是人名「林甲明」、非地名「办公区」、边界错误「某人无权代表星河公司」时，"
            '假设它们的 ID 分别是 1、2、3，必须输出 {"reject_ids":[2],"calibrate_ids":{"3":"星河公司"}}。\n\n'
            f"=== 候选列表 ===\n{candidates_str}\n\n"
            f"=== 文书原文（部分）===\n{text}\n"
        )
