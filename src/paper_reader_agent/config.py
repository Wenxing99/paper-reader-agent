from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppConfig:
    repo_root: Path
    data_root: Path
    papers_root: Path
    exports_root: Path
    obsidian_root: Path
    bridge_url: str
    model: str
    api_key: str
    reasoning_effort: str
    host: str
    port: int
    max_guide_chars: int
    max_context_pages: int
    max_page_context_chars: int
    render_scale: float


def load_config() -> AppConfig:
    repo_root = Path(__file__).resolve().parents[2]
    data_root = repo_root / "data"
    exports_root = data_root / "exports"
    obsidian_root = exports_root / "obsidian"
    return AppConfig(
        repo_root=repo_root,
        data_root=data_root,
        papers_root=data_root / "papers",
        exports_root=exports_root,
        obsidian_root=obsidian_root,
        bridge_url=os.environ.get("PAPER_READER_BRIDGE_URL", "http://127.0.0.1:8765/v1"),
        model=os.environ.get("PAPER_READER_MODEL", "gpt-5.4-mini"),
        api_key=os.environ.get("PAPER_READER_API_KEY", ""),
        reasoning_effort=os.environ.get("PAPER_READER_REASONING_EFFORT", "").strip(),
        host=os.environ.get("PAPER_READER_HOST", "127.0.0.1"),
        port=int(os.environ.get("PAPER_READER_PORT", "8790")),
        max_guide_chars=int(os.environ.get("PAPER_READER_MAX_GUIDE_CHARS", "120000")),
        max_context_pages=int(os.environ.get("PAPER_READER_MAX_CONTEXT_PAGES", "4")),
        max_page_context_chars=int(os.environ.get("PAPER_READER_MAX_PAGE_CONTEXT_CHARS", "2200")),
        render_scale=float(os.environ.get("PAPER_READER_RENDER_SCALE", "1.8")),
    )
