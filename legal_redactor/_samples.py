"""量化样本系统 —— 一键追加，自动积累。

每次点「保存为样本」自动追加到 samples/_auto.sample.json，
不需要命名，不分类。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import Candidate, MappingEntry

SAMPLE_VERSION = "1.0"
DEFAULT_SAMPLES_DIR = Path("samples")
AUTO_SAMPLE_FILE = "_auto.sample.json"
_PROVINCE_ABBRS = frozenset("京津冀晋蒙辽吉黑沪苏浙皖闽赣鲁豫鄂湘粤桂琼渝川贵云藏陕甘青宁新兵")
_COMMON_SURNAME_CHARS = frozenset(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳史唐"
    "费薛雷贺倪汤罗毕郝安常于时傅齐康伍余元顾孟平黄和萧尹姚邵汪祁毛"
    "狄米明计成戴谈宋庞熊纪舒屈项祝董梁杜阮蓝季强贾路娄危江童颜郭梅盛林"
    "钟徐邱骆高夏蔡田樊胡凌霍万柯管卢莫经房裘干解应宗丁宣邓郁单洪包诸左"
    "石崔吉龚程邢裴陆荣翁惠甄曲家封储松段富巫焦巴弓秋仲伊宁仇暴甘厉戎祖"
    "武符刘景詹龙叶幸司黎薄白从赖卓屠池乔阴能苍双闻党谭贡劳姬申冉郦"
    "桂牛寿通边燕浦尚农温庄晏柴瞿阎慕连茹习艾向古易戈廖终居衡步都耿满弘"
    "国文寇广禄阙东欧利师巩聂勾"
)
_COMMON_COMPOUND_SURNAMES = (
    "欧阳", "司马", "上官", "夏侯", "诸葛", "闻人", "东方", "赫连", "皇甫", "尉迟",
    "公羊", "澹台", "公冶", "宗政", "濮阳", "淳于", "单于", "太叔", "申屠", "公孙",
    "仲孙", "轩辕", "令狐", "钟离", "宇文", "长孙", "慕容", "鲜于", "闾丘", "司徒",
    "司空", "端木", "巫马", "公西", "漆雕", "乐正", "拓跋", "夹谷", "谷梁", "南宫",
)
_SHORT_PERSON_DELETE_SAFE_TYPES = {
    "case_number",
    "phone",
    "id_number",
    "bank_account",
    "uscc",
    "email",
}


def _auto_sample_path(samples_dir: str | Path = DEFAULT_SAMPLES_DIR) -> Path:
    return Path(samples_dir) / AUTO_SAMPLE_FILE


def save_sample_auto(
    entries: list[dict[str, str]],
    source: str = "",
    samples_dir: str | Path = DEFAULT_SAMPLES_DIR,
) -> Path:
    """追加样本到自动样本文件。"""
    now = _now_iso()
    dir_path = Path(samples_dir)
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = _auto_sample_path(samples_dir)

    # 加载已有样本
    existing: list[dict] = []
    existing_fallback_time = now
    if file_path.exists():
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            existing = data.get("entries", [])
            existing_fallback_time = (
                data.get("updated_at")
                or data.get("created_at")
                or datetime.fromtimestamp(file_path.stat().st_mtime, timezone.utc).isoformat()
            )
        except (json.JSONDecodeError, KeyError):
            existing = []

    incoming = [_stamp_entry(e, now=now, source=source) for e in entries]

    # 合并：同 original 的条目，新的覆盖旧的
    merged = _merge_entries(existing, incoming, now=now, existing_fallback_time=existing_fallback_time)
    # 整理：移除无效条目 + 排序
    merged = _compact_entries(merged)

    data = {
        "version": SAMPLE_VERSION,
        "updated_at": now,
        "total": len(merged),
        "entries": merged,
    }
    file_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.chmod(file_path, 0o600)
    return file_path


def _merge_entries(
    existing: list[dict],
    incoming: list[dict],
    now: str | None = None,
    existing_fallback_time: str | None = None,
) -> list[dict]:
    """合并样本条目：同 original 的新条目覆盖旧条目。"""
    if now is None:
        now = _now_iso()
    if existing_fallback_time is None:
        existing_fallback_time = now
    # 用 original → entry 索引
    index: dict[str, dict] = {}
    # delete 条目的 original 可能出现在多个 action 中，用更宽松的索引
    for e in existing:
        orig = _entry_original(e)
        if orig:
            index[orig] = _preserve_existing_entry(e, fallback_time=existing_fallback_time)
    for e in incoming:
        orig = _entry_original(e)
        if orig:
            previous = index.get(orig)
            stamped = _stamp_entry(e, now=now)
            if previous:
                stamped["created_at"] = previous.get("created_at") or stamped.get("created_at")
                stamped["first_seen_at"] = previous.get("first_seen_at") or stamped.get("first_seen_at")
            index[orig] = stamped  # 新覆盖旧

    # 最新样本放前面，便于优先处理最近错误。
    result = sorted(index.values(), key=lambda e: (_entry_sort(e), _reverse_time_key(e), _entry_original(e)))
    return result


def _stamp_entry(entry: dict, now: str, source: str = "") -> dict:
    """补齐样本时间字段；兼容旧样本。"""
    stamped = dict(entry)
    created_at = stamped.get("created_at") or stamped.get("first_seen_at") or now
    stamped["created_at"] = created_at
    stamped["first_seen_at"] = stamped.get("first_seen_at") or created_at
    stamped["updated_at"] = now
    stamped["last_seen_at"] = now
    if source and not stamped.get("source"):
        stamped["source"] = source
    if source:
        stamped["last_source"] = source
    return stamped


def _preserve_existing_entry(entry: dict, fallback_time: str) -> dict:
    """Normalize an existing sample without making it look newly updated."""
    preserved = dict(entry)
    created_at = preserved.get("created_at") or preserved.get("first_seen_at") or fallback_time
    updated_at = preserved.get("updated_at") or preserved.get("last_seen_at") or fallback_time
    preserved["created_at"] = created_at
    preserved["first_seen_at"] = preserved.get("first_seen_at") or created_at
    preserved["updated_at"] = updated_at
    preserved["last_seen_at"] = preserved.get("last_seen_at") or updated_at
    return preserved


_LAST_TIMESTAMP: datetime | None = None


def _now_iso() -> str:
    """Return a monotonic UTC timestamp for sample ordering."""
    global _LAST_TIMESTAMP
    current = datetime.now(timezone.utc)
    if _LAST_TIMESTAMP is not None and current <= _LAST_TIMESTAMP:
        current = _LAST_TIMESTAMP + timedelta(microseconds=1)
    _LAST_TIMESTAMP = current
    return current.isoformat()


def _entry_original(e: dict) -> str:
    """提取条目的核心 original 值。"""
    if e.get("action") == "modify":
        return e.get("new_original") or e.get("old_original", "")
    return e.get("original", "")


def _entry_sort(e: dict) -> int:
    order = {"delete": 0, "keep": 1, "modify": 2, "add": 3}
    return order.get(e.get("action", ""), 9)


def _entry_updated_at(e: dict) -> str:
    return str(e.get("updated_at") or e.get("last_seen_at") or e.get("created_at") or e.get("first_seen_at") or "")


def _reverse_time_key(e: dict) -> str:
    value = _entry_updated_at(e)
    return "".join(chr(0x10FFFF - ord(ch)) for ch in value)


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


def is_global_delete_sample_allowed(entry: dict) -> bool:
    """Return whether a delete/old-original sample may suppress future matches globally."""
    original = str(entry.get("original") or entry.get("old_original") or "").strip()
    if not original:
        return False
    if str(entry.get("type") or "") in _SHORT_PERSON_DELETE_SAFE_TYPES:
        return True
    return not _looks_like_short_common_person_name(original)


def _looks_like_short_common_person_name(value: str) -> bool:
    if not re.fullmatch(r"[\u4e00-\u9fa5]{2,3}", value):
        return False
    if any(token in value for token in ("某", "公司", "法院", "项目", "工程")):
        return False
    if len(value) == 3 and value[:2] in _COMMON_COMPOUND_SURNAMES:
        return True
    return value[0] in _COMMON_SURNAME_CHARS


def load_recent_error_samples(
    samples_dir: str | Path | None = None,
    limit: int = 100,
) -> list[dict]:
    """按最新更新时间读取 delete 错误样本，供规则优化优先使用。"""
    if samples_dir is None:
        samples_dir = DEFAULT_SAMPLES_DIR
    entries: list[dict] = []
    for path in _sample_files(samples_dir):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        try:
            file_updated_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        except OSError:
            file_updated_at = _now_iso()
        fallback_time = str(data.get("updated_at") or data.get("created_at") or file_updated_at)
        for entry in data.get("entries", []):
            if entry.get("action") != "delete":
                continue
            stamped = _stamp_entry(
                entry,
                now=entry.get("updated_at")
                or entry.get("last_seen_at")
                or entry.get("created_at")
                or entry.get("first_seen_at")
                or fallback_time,
            )
            stamped["_sample_file"] = str(path)
            entries.append(stamped)
    entries.sort(key=lambda e: (_entry_updated_at(e), _entry_original(e)), reverse=True)
    return entries[:limit]


def load_all_samples(samples_dir: str | Path | None = None) -> tuple[dict[str, str], set[str]]:
    """加载样本 lookup 与 delete/modify-old 黑名单。

    黑名单仅供 few-shot、recent-errors 等优化流程使用；脱敏运行时不会读取。
    """
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
                    if is_global_delete_sample_allowed(entry):
                        blacklist.add(entry.get("original", ""))
                elif action in ("keep", "add"):
                    orig = entry.get("original", "")
                    masked = entry.get("masked", "")
                    if orig and masked and _sample_lookup_allowed(entry, orig, masked):
                        lookup[orig] = masked
                elif action == "modify":
                    old = entry.get("old_original", "")
                    new = entry.get("new_original", "")
                    if old and old != new and is_global_delete_sample_allowed({"type": entry.get("type", ""), "original": old}):
                        blacklist.add(old)
                    if new and entry.get("new_masked") and _sample_lookup_allowed(entry, new, entry["new_masked"]):
                        lookup[new] = entry["new_masked"]
        except (json.JSONDecodeError, KeyError):
            continue

    return lookup, blacklist


def load_sample_blacklist_for_optimization(samples_dir: str | Path | None = None) -> set[str]:
    """Return delete/modify-old blacklist for LLM few-shot and rule tuning only."""
    _, blacklist = load_all_samples(samples_dir)
    return blacklist


def load_trusted_sample_mappings(samples_dir: str | Path | None = None) -> list[MappingEntry]:
    """加载可直接复用的历史脱敏映射。

    只复用 keep/modify 这类来自既有映射校正的样本；add 往往是人工补录的
    临时短语，默认不全局自动替换，避免把普通文本误当实体。
    """
    if samples_dir is None:
        samples_dir = DEFAULT_SAMPLES_DIR

    mappings: list[MappingEntry] = []
    seen: set[str] = set()
    for path in _sample_files(samples_dir):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        for entry in data.get("entries", []):
            action = entry.get("action", "keep")
            if action == "keep":
                original = entry.get("original", "")
                masked = entry.get("masked", "")
            elif action == "modify":
                original = entry.get("new_original", "")
                masked = entry.get("new_masked", "")
            elif action == "add" and _trusted_added_mapping_type(entry):
                original = entry.get("original", "")
                masked = entry.get("masked", "")
            else:
                continue

            if not original or not masked or original in seen or original == masked:
                continue
            seen.add(original)
            mapping_type = _trusted_added_mapping_type(entry) or entry.get("type", "sample")
            mappings.append(
                MappingEntry(
                    type=mapping_type,
                    original=original,
                    masked=masked,
                    role=None,
                    source=f"sample_library:{action}",
                    confidence=1.0,
                    restore_by_default=True,
                )
            )

    return mappings


def _trusted_added_mapping_type(entry: dict) -> str:
    """Only promote added samples when they are a complete, low-ambiguity entity."""
    if entry.get("action") != "add":
        return ""
    original = str(entry.get("original") or "")
    masked = str(entry.get("masked") or "")
    if not _sample_lookup_allowed(entry, original, masked):
        return ""
    if _looks_like_sample_org(original, masked, str(entry.get("type") or "")):
        return "organization"
    if _looks_like_sample_location(original, masked, str(entry.get("type") or "")):
        return "location"
    if _looks_like_sample_person(original, masked, str(entry.get("type") or "")):
        return "person"
    if _looks_like_sample_project(original, masked):
        return "project"
    return ""


def _sample_lookup_allowed(entry: dict, original: str, masked: str) -> bool:
    if not original or not masked or original == masked:
        return False
    if len(original) == 1 and original in _PROVINCE_ABBRS:
        return False
    if str(entry.get("type") or "") == "case_number":
        return False
    return True


def is_sample_lookup_allowed(entry: dict, original: str, masked: str) -> bool:
    """Return whether a sample entry may become a trusted lookup mapping."""
    return _sample_lookup_allowed(entry, original, masked)


def _looks_like_sample_org(original: str, masked: str, sample_type: str) -> bool:
    if not masked.endswith(("公司", "集团")):
        return False
    if sample_type == "organization" and len(original) >= 2:
        return True
    return len(original) >= 3 and (
        original.endswith(("有限责任公司", "股份有限公司", "集团有限公司", "有限公司", "公司", "集团"))
        or "公司" in original
        or "集团" in original
    )


def _looks_like_sample_location(original: str, masked: str, sample_type: str) -> bool:
    if not masked.endswith(("省", "市", "区", "县", "镇", "乡", "村", "社区", "街道")):
        return False
    if sample_type == "location" and len(original) >= 2:
        return True
    if sample_type == "grassroots_org" and len(original) >= 2:
        return True
    return len(original) >= 2 and (
        original.endswith(("省", "市", "区", "县", "镇", "乡", "村", "社区", "街道", "小区"))
        or masked.endswith(("小区", "村", "镇", "县", "区", "市", "省"))
    )


def _looks_like_sample_person(original: str, masked: str, sample_type: str) -> bool:
    if sample_type not in {"person", "manual"}:
        return False
    return 2 <= len(original) <= 4 and bool(re.fullmatch(r"[\u4e00-\u9fa5]某[\u4e00-\u9fa5]?", masked))


def _looks_like_sample_project(original: str, masked: str) -> bool:
    return len(original) >= 3 and masked.endswith(("小区", "项目", "工程"))


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
                    if orig and len(orig) >= 2 and is_global_delete_sample_allowed(entry):
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
