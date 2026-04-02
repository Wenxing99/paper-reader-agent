from __future__ import annotations

import json
import re
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable

import pdfplumber
import pypdfium2 as pdfium

from paper_reader_agent.config import AppConfig
from paper_reader_agent.models import PaperRecord
from paper_reader_agent.services.bridge import request_chat_completion
from paper_reader_agent.services.library import inspect_pdf, resolve_pdf_path, save_paper
from paper_reader_agent.services.obsidian import build_obsidian_export_hint
from paper_reader_agent.services.storage import (
    guide_path,
    metadata_path,
    page_path,
    pages_dir,
    read_json,
    renders_dir,
    write_json,
)


WORDS_X_TOLERANCE = 1.0
WORDS_Y_TOLERANCE = 3.0
LINE_TOP_TOLERANCE = 2.5
CACHE_WARMUP_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="paper-cache")
CACHE_WARMUP_LOCK = Lock()
CACHE_WARMUP_FUTURES: dict[str, Future[Any]] = {}


def ensure_text_cache(config: AppConfig, record: PaperRecord) -> PaperRecord:
    pdf_path = resolve_pdf_path(record)
    if not pdf_path.exists():
        raise FileNotFoundError("原始 PDF 文件不存在。")

    stat = pdf_path.stat()
    current_files = _current_page_files(config, record.id)
    if _is_full_cache_current(record, stat, current_files):
        return record

    title_hint, page_count_hint = inspect_pdf(pdf_path)
    pages_root = pages_dir(config, record.id)
    pages_root.mkdir(parents=True, exist_ok=True)
    expected_files: set[str] = set()

    with pdfplumber.open(str(pdf_path)) as document:
        page_count = len(document.pages) or page_count_hint
        for page_number, page in enumerate(document.pages, start=1):
            payload = _build_page_payload(page, page_number)
            write_json(page_path(config, record.id, page_number), payload)
            expected_files.add(f"{page_number:04d}.json")

    for stale_path in current_files:
        if stale_path.name not in expected_files:
            stale_path.unlink(missing_ok=True)

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
    _save_cache_record(config, record)
    return record


def kickoff_text_cache_warmup(config: AppConfig, record: PaperRecord) -> PaperRecord:
    pdf_path = resolve_pdf_path(record)
    if not pdf_path.exists():
        return record

    stat = pdf_path.stat()
    current_files = _current_page_files(config, record.id)
    if _is_full_cache_current(record, stat, current_files):
        if record.cache_state != "ready":
            record.cache_state = "ready"
            record.updated_at = _now_iso()
            _save_cache_record(config, record)
        return record

    with CACHE_WARMUP_LOCK:
        existing = CACHE_WARMUP_FUTURES.get(record.id)
        if existing and not existing.done():
            if record.cache_state != "warming":
                record.cache_state = "warming"
                record.updated_at = _now_iso()
                _save_cache_record(config, record)
            return record

        record.cache_state = "warming"
        record.updated_at = _now_iso()
        _save_cache_record(config, record)

        future = CACHE_WARMUP_EXECUTOR.submit(_run_cache_warmup, config, record.id)
        CACHE_WARMUP_FUTURES[record.id] = future
        future.add_done_callback(lambda finished, paper_id=record.id: _complete_cache_warmup(config, paper_id, finished))
    return record


def ensure_page_cache(config: AppConfig, record: PaperRecord, page_number: int) -> tuple[PaperRecord, dict[str, Any]]:
    if page_number < 1:
        raise FileNotFoundError("页码必须从 1 开始。")

    pdf_path = resolve_pdf_path(record)
    if not pdf_path.exists():
        raise FileNotFoundError("原始 PDF 文件不存在。")

    stat = pdf_path.stat()
    cached_page_path = page_path(config, record.id, page_number)
    source_is_current = _source_is_current(record, stat)
    cached_payload = read_json(cached_page_path, None) if source_is_current else None
    if cached_payload:
        return record, cached_payload

    with pdfplumber.open(str(pdf_path)) as document:
        page_count = len(document.pages)
        if page_number > page_count:
            raise FileNotFoundError("页码超出范围。")
        payload = _build_page_payload(document.pages[page_number - 1], page_number)

    write_json(cached_page_path, payload)

    record.title = record.title or pdf_path.stem
    record.filename = record.filename or pdf_path.name
    record.page_count = page_count
    record.source_mtime = stat.st_mtime
    record.source_size = stat.st_size
    cached_count = _cached_page_count(config, record.id)
    if cached_count >= page_count:
        record.cache_state = "ready"
    elif record.cache_state == "warming":
        record.cache_state = "warming"
    else:
        record.cache_state = "partial"
    record.updated_at = _now_iso()
    _save_cache_record(config, record)
    return record, payload


def load_page(config: AppConfig, paper_id: str, page_number: int) -> dict[str, Any]:
    payload = read_json(page_path(config, paper_id, page_number), None)
    if payload is None:
        raise FileNotFoundError("页面数据不存在。")
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
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    existing = load_reading_guide(config, record.id)
    if existing and not force and record.guide_state == "ready":
        return existing

    if on_stage:
        on_stage("build_context")

    pages = load_all_pages(config, record.id)
    labeled_text = build_labeled_document_text(pages, config.max_guide_chars)
    if not labeled_text:
        raise RuntimeError("没有可用于生成阅读导图的文本层。")

    if on_stage:
        on_stage("draft_guide")

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
                        "请根据整篇论文内容生成一个结构化阅读导图，只返回 JSON：",
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
                        "要求：",
                        "- 所有字段都用简体中文。",
                        "- 不要写成页面导航，不要把输出做成常驻章节面板文案。",
                        "- one_sentence 要像真正的论文总览，不要空泛。",
                        "- background/problem/innovations/method/results/limitations 每组给 2-5 条。",
                        "- reading_guide 要告诉用户应该先看哪里、再看哪里、哪些部分值得跳读。",
                        "- sections 只保留 4-8 个重要章节或内容单元，page_hint 尽量依据 [Page N] 标记。",
                        "- 不要编造论文里没有的信息。",
                        f"论文标题提示: {record.title}",
                        "论文文本：",
                        labeled_text,
                    ]
                ),
            },
        ],
        max_tokens=2200,
        temperature=0.2,
    )

    if on_stage:
        on_stage("finalize")

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
            raise FileNotFoundError("页码超出范围。")
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
        "cache_state": record.cache_state,
        "guide_state": record.guide_state,
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
        "one_sentence": _first_non_empty(payload.get("one_sentence"), "未生成一句话总结。"),
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


def _current_page_files(config: AppConfig, paper_id: str) -> list[Path]:
    root = pages_dir(config, paper_id)
    return sorted(root.glob("*.json")) if root.exists() else []


def _source_is_current(record: PaperRecord, stat: Any) -> bool:
    return record.source_mtime == stat.st_mtime and record.source_size == stat.st_size


def _is_full_cache_current(record: PaperRecord, stat: Any, current_files: list[Path]) -> bool:
    return (
        record.cache_state == "ready"
        and _source_is_current(record, stat)
        and len(current_files) == int(record.page_count or 0)
    )


def _cached_page_count(config: AppConfig, paper_id: str) -> int:
    return len(_current_page_files(config, paper_id))


def _run_cache_warmup(config: AppConfig, paper_id: str) -> None:
    payload = read_json(metadata_path(config, paper_id), None)
    if not payload:
        return
    record = PaperRecord.from_json(payload)
    ensure_text_cache(config, record)


def _complete_cache_warmup(config: AppConfig, paper_id: str, finished: Future[Any]) -> None:
    with CACHE_WARMUP_LOCK:
        if CACHE_WARMUP_FUTURES.get(paper_id) is finished:
            CACHE_WARMUP_FUTURES.pop(paper_id, None)

    if finished.cancelled() or finished.exception() is None:
        return

    payload = read_json(metadata_path(config, paper_id), None)
    if not payload:
        return

    record = PaperRecord.from_json(payload)
    record.cache_state = "partial" if _cached_page_count(config, paper_id) else "missing"
    record.updated_at = _now_iso()
    _save_cache_record(config, record)


def _save_cache_record(config: AppConfig, record: PaperRecord) -> None:
    latest_payload = read_json(metadata_path(config, record.id), None)
    if isinstance(latest_payload, dict) and latest_payload:
        latest = PaperRecord.from_json(latest_payload)
        record.created_at = latest.created_at or record.created_at
        record.source_path = latest.source_path or record.source_path
        record.storage_mode = latest.storage_mode or record.storage_mode
        record.library_root = latest.library_root or record.library_root
        record.library_relpath = latest.library_relpath or record.library_relpath
        record.guide_state = _merge_cache_guide_state(latest.guide_state, record.guide_state)
    save_paper(config, record)


def _merge_cache_guide_state(latest_state: str, next_state: str) -> str:
    latest = str(latest_state or "").strip().lower()
    proposed = str(next_state or "").strip().lower()
    if latest in {"running", "ready", "failed"}:
        return latest
    if latest == "stale" and proposed == "missing":
        return "missing"
    return proposed or latest or "missing"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
