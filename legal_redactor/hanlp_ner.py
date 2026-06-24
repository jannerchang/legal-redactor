from __future__ import annotations

from functools import lru_cache
from typing import Any

from .models import Candidate


DEFAULT_HANLP_MODEL = "MSRA_NER_ELECTRA_SMALL_ZH"

_LABEL_TO_TYPE = {
    "PERSON": "person",
    "PER": "person",
    "NR": "person",
    "人名": "person",
    "LOCATION": "location",
    "LOC": "location",
    "GPE": "location",
    "NS": "location",
    "地名": "location",
    "ORGANIZATION": "organization",
    "ORG": "organization",
    "NT": "organization",
    "机构名": "organization",
}


def detect_hanlp_ner_candidates(
    text: str,
    model: str = DEFAULT_HANLP_MODEL,
    max_chars: int = 12000,
) -> tuple[list[Candidate], str | None]:
    """Run local HanLP NER and convert entities into redaction candidates.

    HanLP is optional. Missing dependencies, model download failures, or output
    shape differences are reported as warnings and never block redaction.
    """
    if not text.strip():
        return [], None
    scan_text = text[:max_chars]
    try:
        recognizer = _load_hanlp_model(model)
        result = recognizer(scan_text)
        return _candidates_from_hanlp_result(result, scan_text), None
    except ModuleNotFoundError:
        return [], "HanLP 未安装，已跳过本地 HanLP NER"
    except Exception as exc:
        return [], f"HanLP NER 调用失败：{exc}"


@lru_cache(maxsize=4)
def _load_hanlp_model(model: str):
    import hanlp
    from hanlp.pretrained import mtl, ner, tok

    if model == "MSRA_NER_ELECTRA_SMALL_ZH":
        pipeline = hanlp.pipeline()
        pipeline.append(hanlp.load(tok.COARSE_ELECTRA_SMALL_ZH), output_key="tok")
        pipeline.append(hanlp.load(ner.MSRA_NER_ELECTRA_SMALL_ZH), output_key="ner", input_key="tok")
        return pipeline

    model_ref = getattr(ner, model, None) or getattr(mtl, model, None) or model
    return hanlp.load(model_ref)


def _candidates_from_hanlp_result(result: Any, text: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    if isinstance(result, dict):
        _append_document_candidates(candidates, result, text)
    elif isinstance(result, list):
        _append_span_candidates(candidates, result, text)
    return _deduplicate(candidates)


def _append_document_candidates(candidates: list[Candidate], doc: dict, text: str) -> None:
    ner_key = _find_key(doc, "ner")
    if not ner_key:
        return
    ner_items = doc.get(ner_key)
    tok_key = _find_key(doc, "tok")
    tokens = doc.get(tok_key) if tok_key else None
    token_offsets = _token_offsets(text, tokens) if tokens else []

    if not isinstance(ner_items, list):
        return
    if _looks_like_span(ner_items):
        _append_one_span(candidates, ner_items, text)
        return
    if _looks_like_flat_span_list(ner_items):
        for item in ner_items:
            _append_one_span(candidates, item, text, token_offsets, 0)
        return
    for sent_index, sent_ner in enumerate(ner_items):
        if _looks_like_span(sent_ner):
            _append_one_span(candidates, sent_ner, text, token_offsets, sent_index)
        elif isinstance(sent_ner, list):
            for item in sent_ner:
                _append_one_span(candidates, item, text, token_offsets, sent_index)


def _append_span_candidates(candidates: list[Candidate], spans: list, text: str) -> None:
    if _looks_like_span(spans):
        _append_one_span(candidates, spans, text)
        return
    for item in spans:
        if isinstance(item, list) and item and _looks_like_span(item[0]):
            for span in item:
                _append_one_span(candidates, span, text)
        else:
            _append_one_span(candidates, item, text)


def _append_one_span(
    candidates: list[Candidate],
    span: Any,
    text: str,
    token_offsets: list[list[tuple[int, int]]] | None = None,
    sent_index: int = 0,
) -> None:
    entity: str | None = None
    label: str | None = None
    start: int | None = None
    end: int | None = None

    if isinstance(span, dict):
        entity = _first_str(span, "text", "entity", "word", "name")
        label = _first_str(span, "label", "type", "ner")
        start = _first_int(span, "start", "begin", "offset")
        end = _first_int(span, "end")
    elif isinstance(span, (list, tuple)) and len(span) >= 2:
        entity = span[0] if isinstance(span[0], str) else None
        label = span[1] if isinstance(span[1], str) else None
        if len(span) >= 4 and isinstance(span[2], int) and isinstance(span[3], int):
            start, end = _resolve_offsets(text, entity, span[2], span[3], token_offsets, sent_index)
        elif len(span) >= 3 and isinstance(span[2], (list, tuple)) and len(span[2]) >= 2:
            if isinstance(span[2][0], int) and isinstance(span[2][1], int):
                start, end = _resolve_offsets(text, entity, span[2][0], span[2][1], token_offsets, sent_index)

    if not entity or not label:
        return
    entity = entity.strip()
    entity_type = _LABEL_TO_TYPE.get(label.upper()) or _LABEL_TO_TYPE.get(label)
    if entity_type is None or len(entity) < 2:
        return
    if start is None or end is None or start < 0 or end <= start:
        start = text.find(entity)
        end = start + len(entity) if start >= 0 else -1
    if start < 0:
        return
    candidates.append(
        Candidate(
            type=entity_type,
            text=entity,
            start=start,
            end=end,
            source="hanlp_ner",
            confidence=0.88,
            risk_level="medium",
            auto_redact=True,
            reason=f"HanLP NER: {label}",
            metadata={"context": text[max(0, start - 40): min(len(text), end + 40)]},
        )
    )


def _resolve_offsets(
    text: str,
    entity: str | None,
    start: int,
    end: int,
    token_offsets: list[list[tuple[int, int]]] | None,
    sent_index: int,
) -> tuple[int | None, int | None]:
    if entity and 0 <= start < end <= len(text) and text[start:end] == entity:
        return start, end
    if token_offsets and 0 <= sent_index < len(token_offsets):
        sent_offsets = token_offsets[sent_index]
        if 0 <= start < end <= len(sent_offsets):
            return sent_offsets[start][0], sent_offsets[end - 1][1]
    return start, end


def _token_offsets(text: str, tokens: Any) -> list[list[tuple[int, int]]]:
    if not isinstance(tokens, list) or not tokens:
        return []
    sentences = [tokens] if tokens and all(isinstance(item, str) for item in tokens) else tokens
    offsets: list[list[tuple[int, int]]] = []
    cursor = 0
    for sentence in sentences:
        sent_offsets: list[tuple[int, int]] = []
        if not isinstance(sentence, list):
            continue
        for token in sentence:
            if not isinstance(token, str) or not token:
                continue
            start = text.find(token, cursor)
            if start < 0:
                start = text.find(token)
            if start < 0:
                continue
            end = start + len(token)
            sent_offsets.append((start, end))
            cursor = end
        offsets.append(sent_offsets)
    return offsets


def _find_key(doc: dict, prefix: str) -> str | None:
    for key in doc:
        if key == prefix or str(key).startswith(prefix + "/"):
            return str(key)
    return None


def _looks_like_span(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and isinstance(value[0], str)
        and isinstance(value[1], str)
    )


def _looks_like_flat_span_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_looks_like_span(item) for item in value)


def _first_str(data: dict, *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            return value
    return None


def _first_int(data: dict, *keys: str) -> int | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, int):
            return value
    return None


def _deduplicate(candidates: list[Candidate]) -> list[Candidate]:
    best: dict[tuple[str, str, int], Candidate] = {}
    for candidate in candidates:
        key = (candidate.type, candidate.text, candidate.start)
        previous = best.get(key)
        if previous is None or candidate.confidence > previous.confidence:
            best[key] = candidate
    return list(best.values())
