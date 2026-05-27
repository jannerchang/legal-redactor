"""量化样本系统 —— 一键追加，自动积累。

每次点「保存为样本」自动追加到 samples/_auto.sample.json，
不需要命名，不分类。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Candidate

SAMPLE_VERSION = "1.0"
DEFAULT_SAMPLES_DIR = Path("samples")
AUTO_SAMPLE_FILE = "_auto.sample.json"


def _auto_sample_path(samples_dir: str | Path = DEFAULT_SAMPLES_DIR) -> Path:
    return Path(samples_dir) / AUTO_SAMPLE_FILE


def save_sample_auto(
    entries: list[dict[str, str]],
    source: str = "",
    samples_dir: str | Path = DEFAULT_SAMPLES_DIR,
) -> Path:
    """追加样本到自动样本文件。"""
    dir_path = Path(samples_dir)
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = _auto_sample_path(samples_dir)

    # 加载已有样本
    existing: list[dict] = []
    if file_path.exists():
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            existing = data.get("entries", [])
        except (json.JSONDecodeError, KeyError):
            existing = []

    # 合并：同 original 的条目，新的覆盖旧的
    merged = _merge_entries(existing, entries)
    # 整理：移除无效条目 + 排序
    merged = _compact_entries(merged)

    data = {
        "version": SAMPLE_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(merged),
        "entries": merged,
    }
    file_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.chmod(file_path, 0o600)
    return file_path


def _merge_entries(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """合并样本条目：同 original 的新条目覆盖旧条目。"""
    # 用 original → entry 索引
    index: dict[str, dict] = {}
    # delete 条目的 original 可能出现在多个 action 中，用更宽松的索引
    for e in existing:
        orig = _entry_original(e)
        if orig:
            index[orig] = e
    for e in incoming:
        orig = _entry_original(e)
        if orig:
            index[orig] = e  # 新覆盖旧

    # 按 action 分组排序：delete 放前面（便于查看哪些被拉黑了）
    result = sorted(index.values(), key=lambda e: (_entry_sort(e), _entry_original(e)))
    return result


def _entry_original(e: dict) -> str:
    """提取条目的核心 original 值。"""
    if e.get("action") == "modify":
        return e.get("new_original") or e.get("old_original", "")
    return e.get("original", "")


def _entry_sort(e: dict) -> int:
    order = {"delete": 0, "keep": 1, "modify": 2, "add": 3}
    return order.get(e.get("action", ""), 9)


def _compact_entries(entries: list[dict]) -> list[dict]:
    """整理条目：过滤空值、重复。"""
    seen = set()
    result = []
    for e in entries:
        orig = _entry_original(e)
        if not orig:
            continue
        action = e.get("action", "")
        # delete 条目不需要 masked
        if action == "delete":
            key = (action, orig)
        elif action in ("keep", "add"):
            masked = e.get("masked", "")
            if not masked:
                continue
            key = (action, orig, masked)
        elif action == "modify":
            new_masked = e.get("new_masked", "")
            if not new_masked:
                continue
            key = (action, orig, new_masked)
        else:
            continue
        if key in seen:
            continue
        seen.add(key)
        result.append(e)
    return result


def load_all_samples(samples_dir: str | Path | None = None) -> tuple[dict[str, str], set[str]]:
    """加载所有样本，返回 (original→masked, 黑名单)。"""
    if samples_dir is None:
        samples_dir = DEFAULT_SAMPLES_DIR
    lookup: dict[str, str] = {}
    blacklist: set[str] = set()

    for path in _sample_files(samples_dir):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for entry in data.get("entries", []):
                action = entry.get("action", "keep")
                if action == "delete":
                    blacklist.add(entry.get("original", ""))
                elif action in ("keep", "add"):
                    orig = entry.get("original", "")
                    masked = entry.get("masked", "")
                    if orig and masked:
                        lookup[orig] = masked
                elif action == "modify":
                    old = entry.get("old_original", "")
                    new = entry.get("new_original", "")
                    if old and old != new:
                        blacklist.add(old)
                    if new and entry.get("new_masked"):
                        lookup[new] = entry["new_masked"]
        except (json.JSONDecodeError, KeyError):
            continue

    return lookup, blacklist


def _sample_files(samples_dir: str | Path | None = None) -> list[Path]:
    if samples_dir is None:
        samples_dir = DEFAULT_SAMPLES_DIR
    dir_path = Path(samples_dir)
    if not dir_path.exists():
        return []
    return sorted(dir_path.glob("*.sample.json"))


def detect_sample_candidates(
    text: str,
    samples_dir: str | Path | None = None,
) -> list[Candidate]:
    """在文本中查找样本库精确匹配，返回高置信度候选。"""
    if samples_dir is None:
        samples_dir = DEFAULT_SAMPLES_DIR
    sample_lookup, _ = load_all_samples(samples_dir)
    if not sample_lookup:
        return []

    candidates: list[Candidate] = []
    for original in sorted(sample_lookup, key=len, reverse=True):
        masked = sample_lookup[original]
        start = 0
        while True:
            idx = text.find(original, start)
            if idx < 0:
                break
            candidates.append(
                Candidate(
                    type="sample_match",
                    text=original,
                    start=idx,
                    end=idx + len(original),
                    source="sample_db",
                    confidence=1.0,
                    risk_level="medium",
                    auto_redact=True,
                    reason=f"样本库 → {masked}",
                    suggested_mask_type=masked,
                    metadata={"sample_masked": masked},
                )
            )
            start = idx + 1
    return candidates


def get_few_shot_examples(samples_dir: str | Path | None = None, max_examples: int = 8) -> str:
    """从样本库中提取典型的正样本与负（Reject）样本，用于注入 LLM few-shot prompt。"""
    if samples_dir is None:
        samples_dir = DEFAULT_SAMPLES_DIR
        
    positive_examples: list[dict] = []
    negative_examples: list[dict] = []
    
    for path in _sample_files(samples_dir):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for entry in data.get("entries", []):
                action = entry.get("action", "keep")
                t = entry.get("type", "other")
                if action == "delete":
                    orig = entry.get("original", "")
                    if orig and len(orig) >= 2:
                        negative_examples.append({"original": orig, "type": t})
                elif action in ("keep", "add", "modify"):
                    orig = entry.get("original") or entry.get("new_original", "")
                    masked = entry.get("masked") or entry.get("new_masked", "")
                    if orig and masked and len(orig) >= 2:
                        positive_examples.append({"original": orig, "masked": masked, "type": t})
        except Exception:
            continue
            
    # 去重
    seen_pos = set()
    dedup_pos = []
    for e in positive_examples:
        if e["original"] not in seen_pos:
            seen_pos.add(e["original"])
            dedup_pos.append(e)
            
    seen_neg = set()
    dedup_neg = []
    for e in negative_examples:
        if e["original"] not in seen_neg:
            seen_neg.add(e["original"])
            dedup_neg.append(e)
            
    # 限制样本数量，选择代表性子集
    pos_sub = dedup_pos[:max_examples]
    neg_sub = dedup_neg[:max_examples]
    
    if not pos_sub and not neg_sub:
        return ""
        
    lines = ["=== 历史脱敏与纠错样本参考 (Few-shot Learning Examples) ==="]
    
    if pos_sub:
        lines.append("【正确实体提取与脱敏示例】：")
        for e in pos_sub:
            type_label = {"person": "人名", "organization": "公司机构", "location": "地名"}.get(e["type"], e["type"])
            lines.append(f'  - 类型: {type_label}, 原文: 「{e["original"]}」 -> 建议脱敏替换为: 「{e["masked"]}」')
            
    if neg_sub:
        lines.append("\n【误匹配/纠错过滤（应放入 reject 列表）示例】：")
        for e in neg_sub:
            type_label = {"person": "人名", "organization": "公司机构", "location": "地名"}.get(e["type"], e["type"])
            lines.append(f'  - 类型: {type_label}, 误匹配短语: 「{e["original"]}」 -> 判定：【非真实实体，属于口语或动作短语】，必须放入 reject 数组进行过滤')
            
    return "\n".join(lines)
