from __future__ import annotations

import re
from typing import Any

from paper_reader_agent.config import AppConfig


TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}|[\u4e00-\u9fff]{1,4}|\d+(?:\.\d+)?")
STOP_WORDS = {
    "the",
    "and",
    "that",
    "with",
    "from",
    "this",
    "into",
    "have",
    "using",
    "what",
    "which",
    "when",
    "where",
    "how",
    "why",
    "paper",
    "about",
}


def build_chat_context(
    config: AppConfig,
    *,
    paper_title: str,
    reading_guide: dict[str, Any] | None,
    pages: list[dict[str, Any]],
    question: str,
    current_page: int,
) -> str:
    lines = [f"论文标题: {paper_title}"]
    if reading_guide:
        lines.append("阅读导图:")
        lines.extend(_format_guide(reading_guide))
    else:
        lines.append("阅读导图: 尚未生成，以下使用论文正文摘录作为上下文。")

    relevant_pages = pick_relevant_pages(
        question,
        pages,
        current_page=current_page,
        limit=config.max_context_pages,
    )
    if relevant_pages:
        lines.append("相关页面摘录:")
        for page in relevant_pages:
            excerpt = clip_text(str(page.get("text") or ""), config.max_page_context_chars)
            lines.append(f"[Page {page.get('page_number')}] {excerpt}")

    if current_page > 0:
        current_payload = next((page for page in pages if page.get("page_number") == current_page), None)
        if current_payload and current_payload not in relevant_pages:
            excerpt = clip_text(str(current_payload.get("text") or ""), config.max_page_context_chars)
            if excerpt:
                lines.append(f"当前阅读页（额外上下文）[Page {current_page}]: {excerpt}")

    return "\n".join(lines)


def build_selection_context(
    config: AppConfig,
    *,
    paper_title: str,
    reading_guide: dict[str, Any] | None,
    page_payload: dict[str, Any] | None,
) -> str:
    lines = [f"论文标题: {paper_title}"]
    if reading_guide:
        lines.append(f"一句话总览: {reading_guide.get('one_sentence') or ''}")
        innovations = reading_guide.get("innovations") or []
        if innovations:
            lines.append("核心创新:")
            for item in innovations[:3]:
                lines.append(f"- {item}")
    if page_payload:
        excerpt = clip_text(str(page_payload.get("text") or ""), config.max_page_context_chars)
        if excerpt:
            lines.append(f"当前页 [Page {page_payload.get('page_number')}]: {excerpt}")
    return "\n".join(lines)


def pick_relevant_pages(
    question: str,
    pages: list[dict[str, Any]],
    *,
    current_page: int,
    limit: int,
) -> list[dict[str, Any]]:
    if not pages:
        return []

    query_tokens = tokenize(question)
    scored: list[tuple[float, dict[str, Any]]] = []

    for page in pages:
        text = str(page.get("text") or "")
        page_number = int(page.get("page_number") or 0)
        score = score_page(query_tokens, text)
        if page_number and page_number == current_page:
            score += 1.5
        if page_number == 1:
            score += 0.5
        scored.append((score, page))

    if query_tokens and any(score > 0 for score, _ in scored):
        ranked = sorted(scored, key=lambda item: (-item[0], int(item[1].get("page_number") or 0)))
        selected = [page for score, page in ranked if score > 0][:limit]
    else:
        preferred_numbers = []
        if pages:
            preferred_numbers.append(1)
        if current_page > 0:
            preferred_numbers.append(current_page)
        if len(pages) > 2:
            preferred_numbers.append(min(len(pages), max(1, len(pages) // 2)))
        if len(pages) > 1:
            preferred_numbers.append(len(pages))
        deduped = []
        seen = set()
        for page_number in preferred_numbers:
            if page_number not in seen:
                deduped.append(page_number)
                seen.add(page_number)
        selected = [page for page in pages if int(page.get("page_number") or 0) in deduped][:limit]

    return selected


def score_page(query_tokens: list[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    haystack = text.lower()
    score = 0.0
    for token in query_tokens:
        count = haystack.count(token)
        if count:
            score += min(count, 3)
            if len(token) > 6:
                score += 0.4
    return score


def tokenize(text: str) -> list[str]:
    tokens = [token.lower() for token in TOKEN_PATTERN.findall(text or "")]
    cleaned = [token for token in tokens if token not in STOP_WORDS]
    return cleaned[:24]


def clip_text(text: str, max_chars: int) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "…"


def _format_guide(guide: dict[str, Any]) -> list[str]:
    lines = []
    one_sentence = str(guide.get("one_sentence") or "").strip()
    if one_sentence:
        lines.append(f"- 一句话总结: {one_sentence}")
    mapping = [
        ("background", "研究背景"),
        ("problem", "核心问题"),
        ("innovations", "创新点"),
        ("method", "方法"),
        ("results", "结果"),
        ("limitations", "局限"),
    ]
    for key, label in mapping:
        items = guide.get(key) or []
        if items:
            joined = "；".join(str(item).strip() for item in items[:3] if str(item).strip())
            if joined:
                lines.append(f"- {label}: {joined}")
    return lines
