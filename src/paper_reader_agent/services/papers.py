from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pdfplumber
import pypdfium2 as pdfium

from paper_reader_agent.config import AppConfig
from paper_reader_agent.models import PaperRecord
from paper_reader_agent.services.bridge import request_chat_completion
from paper_reader_agent.services.library import inspect_pdf, resolve_pdf_path, save_paper
from paper_reader_agent.services.obsidian import build_obsidian_export_hint
from paper_reader_agent.services.storage import guide_path, page_path, pages_dir, read_json, renders_dir, write_json


WORDS_X_TOLERANCE = 1.0
WORDS_Y_TOLERANCE = 3.0
LINE_TOP_TOLERANCE = 2.5


def ensure_text_cache(config: AppConfig, record: PaperRecord) -> PaperRecord:
    pdf_path = resolve_pdf_path(record)
    if not pdf_path.exists():
        raise FileNotFoundError("åŽŸå§‹ PDF æ–‡ä»¶ä¸å­˜åœ¨ã€‚")

    stat = pdf_path.stat()
    pages_root = pages_dir(config, record.id)
    current_files = sorted(pages_root.glob("*.json")) if pages_root.exists() else []
    cache_is_current = (
        record.cache_state == "ready"
        and record.source_mtime == stat.st_mtime
        and record.source_size == stat.st_size
        and len(current_files) == int(record.page_count or 0)
    )
    if cache_is_current:
        return record

    title_hint, page_count_hint = inspect_pdf(pdf_path)

    pages_root.mkdir(parents=True, exist_ok=True)
    for stale_path in current_files:
        stale_path.unlink(missing_ok=True)

    with pdfplumber.open(str(pdf_path)) as document:
        page_count = len(document.pages) or page_count_hint
        for page_number, page in enumerate(document.pages, start=1):
            payload = _build_page_payload(page, page_number)
            write_json(page_path(config, record.id, page_number), payload)

    render_root = renders_dir(config, record.id)
    if render_root.exists():
        for stale_image in render_root.glob("*.png"):
            stale_image.unlink(missing_ok=True)

    record.title = title_hint or record.title or pdf_path.stem
    record.filename = record.filename or pdf_path.name
    record.page_count = page_count
    record.source_mtime = stat.st_mtime
    record.source_size = stat.st_size
    record.cache_state = "ready"
    if record.guide_state == "stale":
        record.guide_state = "missing"
    record.updated_at = _now_iso()
    save_paper(config, record)
    return record


def load_page(config: AppConfig, paper_id: str, page_number: int) -> dict[str, Any]:
    payload = read_json(page_path(config, paper_id, page_number), None)
    if payload is None:
        raise FileNotFoundError("é¡µæ•°æ®ä¸å­˜åœ¨ã€‚")
    return payload


def load_all_pages(config: AppConfig, paper_id: str) -> list[dict[str, Any]]:
    root = pages_dir(config, paper_id)
    pages = [read_json(path, {}) for path in sorted(root.glob("*.json"))]
    return [page for page in pages if page]


def load_reading_guide(config: AppConfig, paper_id: str) -> dict[str, Any] | None:
    payload = read_json(guide_path(config, paper_id), None)
    return payload if payload else None


def generate_reading_guide(
    config: AppConfig,
    bridge: dict[str, str],
    record: PaperRecord,
    *,
    force: bool = False,
) -> dict[str, Any]:
    existing = load_reading_guide(config, record.id)
    if existing and not force and record.guide_state == "ready":
        return existing

    pages = load_all_pages(config, record.id)
    labeled_text = build_labeled_document_text(pages, config.max_guide_chars)
    if not labeled_text:
        raise RuntimeError("æ²¡æœ‰å¯ç”¨äºŽç”Ÿæˆé˜…è¯»å¯¼å›¾çš„æ–‡æœ¬å±‚ã€‚")

    raw = request_chat_completion(
        bridge,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an academic reading assistant. "
                    "Return valid JSON only. Write all values in Simplified Chinese."
                ),
            },
            {
                "role": "user",
                "content": "\n".join(
                    [
                        "è¯·æ ¹æ®æ•´ç¯‡è®ºæ–‡å†…å®¹ç”Ÿæˆä¸€ä¸ªç»“æž„åŒ–é˜…è¯»å¯¼å›¾ï¼Œåªè¿”å›ž JSONï¼š",
                        "{",
                        '  "paper_title": "string",',
                        '  "one_sentence": "string",',
                        '  "background": ["string"],',
                        '  "problem": ["string"],',
                        '  "innovations": ["string"],',
                        '  "method": ["string"],',
                        '  "results": ["string"],',
                        '  "limitations": ["string"],',
                        '  "reading_guide": ["string"],',
                        '  "sections": [{"title": "string", "page_hint": 1, "summary": "string"}]',
                        "}",
                        "è¦æ±‚ï¼š",
                        "- æ‰€æœ‰å­—æ®µéƒ½ç”¨ç®€ä½“ä¸­æ–‡ã€‚",
                        "- ä¸è¦å†™æˆé¡µé¢å¯¼èˆªï¼Œä¸è¦æŠŠè¾“å‡ºåšæˆå¸¸é©»ç« èŠ‚é¢æ¿æ–‡æ¡ˆã€‚",
                        "- one_sentence è¦åƒçœŸæ­£çš„è®ºæ–‡æ€»è§ˆï¼Œä¸è¦ç©ºæ³›ã€‚",
                        "- background/problem/innovations/method/results/limitations æ¯ç»„ç»™ 2-5 æ¡ã€‚",
                        "- reading_guide è¦å‘Šè¯‰ç”¨æˆ·åº”è¯¥å…ˆçœ‹å“ªé‡Œã€å†çœ‹å“ªé‡Œã€å“ªäº›éƒ¨åˆ†å€¼å¾—è·³è¯»ã€‚",
                        "- sections åªä¿ç•™ 4-8 ä¸ªé‡è¦ç« èŠ‚æˆ–å†…å®¹å•å…ƒï¼Œpage_hint å°½é‡ä¾æ® [Page N] æ ‡è®°ã€‚",
                        "- ä¸è¦ç¼–é€ è®ºæ–‡é‡Œæ²¡æœ‰çš„ä¿¡æ¯ã€‚",
                        f"è®ºæ–‡æ ‡é¢˜æç¤º: {record.title}",
                        "è®ºæ–‡æ–‡æœ¬ï¼š",
                        labeled_text,
                    ]
                ),
            },
        ],
        max_tokens=2200,
        temperature=0.2,
    )

    normalized = normalize_reading_guide(_parse_loose_json(raw), record.title)
    normalized["model"] = bridge["model"]
    normalized["generated_at"] = _now_iso()
    write_json(guide_path(config, record.id), normalized)

    record.guide_state = "ready"
    record.updated_at = _now_iso()
    save_paper(config, record)
    return normalized


def render_page_image(config: AppConfig, record: PaperRecord, page_number: int) -> Path:
    output_dir = renders_dir(config, record.id)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{page_number:04d}.png"
    if output_path.exists():
        return output_path

    pdf_path = resolve_pdf_path(record)
    document = pdfium.PdfDocument(str(pdf_path))
    try:
        if page_number < 1 or page_number > len(document):
            raise FileNotFoundError("é¡µç è¶…å‡ºèŒƒå›´ã€‚")
        page = document[page_number - 1]
        try:
            bitmap = page.render(scale=config.render_scale)
            try:
                image = bitmap.to_pil()
                try:
                    image.save(output_path, format="PNG")
                finally:
                    image.close()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()
    return output_path


def build_document_payload(config: AppConfig, record: PaperRecord, *, include_guide: bool) -> dict[str, Any]:
    guide = load_reading_guide(config, record.id) if include_guide else None
    pdf_path = resolve_pdf_path(record)
    return {
        "id": record.id,
        "title": record.title,
        "filename": record.filename,
        "page_count": record.page_count,
        "storage_mode": record.storage_mode,
        "source_label": record.library_relpath or record.filename,
        "source_exists": pdf_path.exists(),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "has_text_cache": record.cache_state == "ready",
        "has_reading_guide": bool(guide),
        "reading_guide": guide,
        "obsidian_hint": build_obsidian_export_hint(record),
    }


def build_labeled_document_text(pages: list[dict[str, Any]], max_chars: int) -> str:
    chunks: list[str] = []
    total = 0
    for page in pages:
        text = str(page.get("text") or "").strip()
        if not text:
            continue
        chunk = f"[Page {page.get('page_number')}]\n{text}\n"
        if chunks and total + len(chunk) > max_chars:
            break
        chunks.append(chunk)
        total += len(chunk)
    return "\n".join(chunks).strip()


def normalize_reading_guide(payload: dict[str, Any], title_hint: str) -> dict[str, Any]:
    return {
        "paper_title": _first_non_empty(payload.get("paper_title"), title_hint, "Untitled"),
        "one_sentence": _first_non_empty(payload.get("one_sentence"), "æœªç”Ÿæˆä¸€å¥è¯æ€»ç»“ã€‚"),
        "background": _string_list(payload.get("background")),
        "problem": _string_list(payload.get("problem")),
        "innovations": _string_list(payload.get("innovations")),
        "method": _string_list(payload.get("method")),
        "results": _string_list(payload.get("results")),
        "limitations": _string_list(payload.get("limitations")),
        "reading_guide": _string_list(payload.get("reading_guide")),
        "sections": _normalize_sections(payload.get("sections")),
    }


def _build_page_payload(page: pdfplumber.page.Page, page_number: int) -> dict[str, Any]:
    text = _clean_text(page.extract_text(x_tolerance=WORDS_X_TOLERANCE, y_tolerance=WORDS_Y_TOLERANCE) or "")
    lines = _extract_lines(page)
    return {
        "page_number": page_number,
        "width": round(float(page.width), 3),
        "height": round(float(page.height), 3),
        "text": text,
        "lines": lines,
        "has_text_layer": bool(lines),
    }


def _extract_lines(page: pdfplumber.page.Page) -> list[dict[str, Any]]:
    raw_words = page.extract_words(
        x_tolerance=WORDS_X_TOLERANCE,
        y_tolerance=WORDS_Y_TOLERANCE,
        keep_blank_chars=False,
        use_text_flow=False,
    )
    if not raw_words:
        return []

    words = sorted(raw_words, key=lambda item: (float(item["top"]), float(item["x0"])))
    grouped: list[dict[str, Any]] = []

    for word in words:
        text = re.sub(r"\s+", " ", str(word.get("text") or "")).strip()
        if not text:
            continue

        x0 = float(word["x0"])
        x1 = float(word["x1"])
        top = float(word["top"])
        bottom = float(word["bottom"])
        height = max(bottom - top, 8.0)

        bucket = grouped[-1] if grouped else None
        if bucket and _same_visual_line(bucket, x0=x0, top=top, bottom=bottom, height=height):
            bucket["parts"].append(text)
            bucket["x1"] = max(bucket["x1"], x1)
            bucket["bottom"] = max(bucket["bottom"], bottom)
            bucket["font_size"] = max(bucket["font_size"], height)
            continue

        grouped.append(
            {
                "parts": [text],
                "x0": x0,
                "x1": x1,
                "top": top,
                "bottom": bottom,
                "font_size": height,
            }
        )

    lines = []
    for index, bucket in enumerate(grouped, start=1):
        text = " ".join(bucket["parts"]).strip()
        if not text:
            continue
        lines.append(
            {
                "id": index,
                "text": text,
                "x": round(bucket["x0"], 3),
                "y": round(bucket["top"], 3),
                "width": round(bucket["x1"] - bucket["x0"], 3),
                "height": round(bucket["bottom"] - bucket["top"], 3),
                "font_size": round(bucket["font_size"], 3),
            }
        )
    return lines


def _same_visual_line(bucket: dict[str, Any], *, x0: float, top: float, bottom: float, height: float) -> bool:
    same_row = abs(top - bucket["top"]) <= LINE_TOP_TOLERANCE and abs(bottom - bucket["bottom"]) <= LINE_TOP_TOLERANCE
    if not same_row:
        return False

    gap = x0 - bucket["x1"]
    max_gap = max(24.0, height * 3.5)
    return -1.0 <= gap <= max_gap


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_loose_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items = []
    for entry in value[:8]:
        text = str(entry or "").strip()
        if text:
            items.append(text)
    return items


def _normalize_sections(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items = []
    for entry in value[:10]:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        summary = str(entry.get("summary") or "").strip()
        try:
            page_hint = int(entry.get("page_hint") or 0)
        except Exception:
            page_hint = 0
        if title:
            items.append(
                {
                    "title": title,
                    "summary": summary,
                    "page_hint": page_hint if page_hint > 0 else None,
                }
            )
    return items


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
