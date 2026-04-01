from __future__ import annotations

import re
from typing import Any

from paper_reader_agent.models import PaperRecord


def build_obsidian_export_hint(record: PaperRecord) -> dict[str, Any]:
    slug = slugify(record.title or record.filename)
    return {
        "ready": True,
        "note_slug": slug,
        "suggested_markdown_path": f"papers/{slug}.md",
    }


def slugify(value: str) -> str:
    text = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE).strip().lower()
    text = re.sub(r"[-\s]+", "-", text)
    return text or "paper-note"
