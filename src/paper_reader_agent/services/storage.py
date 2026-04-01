from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from paper_reader_agent.config import AppConfig


def ensure_repo_dirs(config: AppConfig) -> None:
    config.papers_root.mkdir(parents=True, exist_ok=True)
    config.obsidian_root.mkdir(parents=True, exist_ok=True)


def paper_dir(config: AppConfig, paper_id: str) -> Path:
    return config.papers_root / paper_id


def metadata_path(config: AppConfig, paper_id: str) -> Path:
    return paper_dir(config, paper_id) / "metadata.json"


def guide_path(config: AppConfig, paper_id: str) -> Path:
    return paper_dir(config, paper_id) / "reading_guide.json"


def pages_dir(config: AppConfig, paper_id: str) -> Path:
    return paper_dir(config, paper_id) / "pages"


def page_path(config: AppConfig, paper_id: str, page_number: int) -> Path:
    return pages_dir(config, paper_id) / f"{page_number:04d}.json"


def renders_dir(config: AppConfig, paper_id: str) -> Path:
    return paper_dir(config, paper_id) / "renders"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
