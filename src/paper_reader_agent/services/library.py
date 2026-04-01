from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import abort
from pypdf import PdfReader
from werkzeug.datastructures import FileStorage

from paper_reader_agent.config import AppConfig
from paper_reader_agent.models import PaperRecord
from paper_reader_agent.services.storage import ensure_repo_dirs, metadata_path, paper_dir, read_json, write_json


def list_papers(config: AppConfig) -> list[PaperRecord]:
    ensure_repo_dirs(config)
    records: list[PaperRecord] = []
    for candidate in config.papers_root.glob("*/metadata.json"):
        try:
            payload = read_json(candidate, {})
            record = PaperRecord.from_json(payload)
            records.append(record)
        except Exception:
            continue
    records.sort(key=lambda item: item.updated_at or "", reverse=True)
    return records


def get_paper(config: AppConfig, paper_id: str) -> PaperRecord:
    path = metadata_path(config, paper_id)
    if not path.exists():
        abort(404)
    return PaperRecord.from_json(read_json(path, {}))


def save_paper(config: AppConfig, record: PaperRecord) -> None:
    write_json(metadata_path(config, record.id), record.to_json())


def scan_library(config: AppConfig, folder_path: str) -> list[PaperRecord]:
    root = Path(folder_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError("论文目录不存在，或不是一个有效文件夹。")

    records: list[PaperRecord] = []
    for pdf_path in sorted(root.rglob("*.pdf")):
        if not pdf_path.is_file():
            continue
        record = register_linked_pdf(config, pdf_path, library_root=root)
        records.append(record)
    records.sort(key=lambda item: item.updated_at or "", reverse=True)
    return records


def register_linked_pdf(config: AppConfig, pdf_path: Path, *, library_root: Path) -> PaperRecord:
    resolved = pdf_path.resolve()
    stat = resolved.stat()
    paper_id = hashlib.sha1(str(resolved).lower().encode("utf-8")).hexdigest()[:12]
    now = _now_iso()
    title, page_count = inspect_pdf(resolved)

    existing_payload = read_json(metadata_path(config, paper_id), None)
    if existing_payload:
        record = PaperRecord.from_json(existing_payload)
        file_changed = record.source_mtime != stat.st_mtime or record.source_size != stat.st_size
        record.title = title or record.title or resolved.stem
        record.filename = resolved.name
        record.source_path = str(resolved)
        record.page_count = page_count or record.page_count
        record.updated_at = now
        record.source_mtime = stat.st_mtime
        record.source_size = stat.st_size
        record.library_root = str(library_root)
        record.library_relpath = str(resolved.relative_to(library_root))
        if file_changed:
            record.cache_state = "stale" if record.cache_state == "ready" else "missing"
            record.guide_state = "stale" if record.guide_state == "ready" else "missing"
    else:
        record = PaperRecord(
            id=paper_id,
            title=title or resolved.stem,
            filename=resolved.name,
            source_path=str(resolved),
            storage_mode="linked",
            page_count=page_count,
            created_at=now,
            updated_at=now,
            source_mtime=stat.st_mtime,
            source_size=stat.st_size,
            cache_state="missing",
            guide_state="missing",
            library_root=str(library_root),
            library_relpath=str(resolved.relative_to(library_root)),
        )

    save_paper(config, record)
    return record


def import_uploaded_pdf(config: AppConfig, file: FileStorage) -> PaperRecord:
    filename = (file.filename or "").strip()
    if not filename:
        raise ValueError("请选择一个 PDF 文件。")
    if not filename.lower().endswith(".pdf"):
        raise ValueError("目前只支持 PDF 文件。")

    ensure_repo_dirs(config)
    paper_id = uuid.uuid4().hex[:12]
    target_dir = paper_dir(config, paper_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = target_dir / "paper.pdf"
    file.save(pdf_path)
    stat = pdf_path.stat()
    now = _now_iso()
    title, page_count = inspect_pdf(pdf_path)
    record = PaperRecord(
        id=paper_id,
        title=title or Path(filename).stem,
        filename=filename,
        source_path=str(pdf_path.resolve()),
        storage_mode="copied",
        page_count=page_count,
        created_at=now,
        updated_at=now,
        source_mtime=stat.st_mtime,
        source_size=stat.st_size,
        cache_state="missing",
        guide_state="missing",
    )
    save_paper(config, record)
    return record


def resolve_pdf_path(record: PaperRecord) -> Path:
    return Path(record.source_path).expanduser().resolve()


def inspect_pdf(pdf_path: Path) -> tuple[str, int]:
    reader = PdfReader(str(pdf_path))
    metadata = reader.metadata or {}
    title = str(getattr(metadata, "title", "") or metadata.get("/Title") or "").strip()
    page_count = len(reader.pages)
    return title, page_count


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
