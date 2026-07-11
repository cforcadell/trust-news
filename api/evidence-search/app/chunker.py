import re
from typing import Any, Dict, List


SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def split_sentences(text: str) -> List[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []
    sentences = [part.strip() for part in SENTENCE_BOUNDARY_RE.split(normalized) if part.strip()]
    return sentences or [normalized]


def chunk_text(source_id: str, text: str, chunk_size_chars: int = 1200, overlap_chars: int = 200) -> List[Dict[str, Any]]:
    """Create stable sentence-oriented chunks with bounded character overlap."""
    sentences = split_sentences(text)
    if not sentences:
        return []

    chunk_size_chars = max(1, int(chunk_size_chars or 1200))
    overlap_chars = max(0, int(overlap_chars or 0))
    chunks: List[Dict[str, Any]] = []
    current: List[str] = []

    for sentence in sentences:
        candidate = _normalize_text(" ".join(current + [sentence]))
        if current and len(candidate) > chunk_size_chars:
            chunk = _normalize_text(" ".join(current))
            chunks.append(_make_chunk(source_id, len(chunks), chunk))
            current = _overlap_sentences(current, overlap_chars)
        current.append(sentence)

        while len(_normalize_text(" ".join(current))) > chunk_size_chars * 1.5 and len(current) == 1:
            long_sentence = current.pop()
            slice_text = long_sentence[:chunk_size_chars].strip()
            chunks.append(_make_chunk(source_id, len(chunks), slice_text))
            remainder = long_sentence[max(0, chunk_size_chars - overlap_chars):].strip()
            current = [remainder] if remainder else []

    if current:
        chunks.append(_make_chunk(source_id, len(chunks), _normalize_text(" ".join(current))))
    return chunks


def _make_chunk(source_id: str, zero_based_index: int, text: str) -> Dict[str, Any]:
    return {
        "chunk_index": zero_based_index + 1,
        "chunk_id": f"{source_id}-chunk-{zero_based_index + 1}",
        "text": text,
        "char_length": len(text),
    }


def _overlap_sentences(sentences: List[str], overlap_chars: int) -> List[str]:
    if overlap_chars <= 0:
        return []
    kept: List[str] = []
    total = 0
    for sentence in reversed(sentences):
        kept.insert(0, sentence)
        total += len(sentence) + 1
        if total >= overlap_chars:
            break
    return kept


def build_context_windows(
    source_id: str,
    chunks: List[Dict[str, Any]],
    ranked_chunks: List[Dict[str, Any]],
    max_contexts: int = 2,
    before: int = 1,
    after: int = 1,
    min_context_chars: int = 120,
) -> List[Dict[str, Any]]:
    """Build deduplicated context windows around selected ranked chunks."""
    contexts: List[Dict[str, Any]] = []
    used_windows: List[set[str]] = []
    chunk_by_id = {chunk["chunk_id"]: chunk for chunk in chunks}

    for ranked in ranked_chunks:
        selected = chunk_by_id.get(ranked.get("chunk_id"))
        if not selected:
            continue
        idx = int(selected["chunk_index"]) - 1
        start = max(0, idx - max(0, int(before or 0)))
        end = min(len(chunks), idx + max(0, int(after or 0)) + 1)
        window_chunks = chunks[start:end]
        included_ids = [chunk["chunk_id"] for chunk in window_chunks]
        included_set = set(included_ids)
        if any(included_set == previous or included_set.issubset(previous) or previous.issubset(included_set) for previous in used_windows):
            continue

        text = _normalize_text(" ".join(chunk["text"] for chunk in window_chunks))
        if len(text) < min_context_chars and len(chunks) > len(window_chunks):
            continue

        used_windows.append(included_set)
        contexts.append({
            "context_id": f"{source_id}-context-{len(contexts) + 1}",
            "selected_chunk_id": selected["chunk_id"],
            "included_chunk_ids": included_ids,
            "text": text,
            "score": ranked.get("score"),
            "origin": "html_main_text",
            "char_length": len(text),
        })
        if len(contexts) >= max_contexts:
            break

    return contexts
