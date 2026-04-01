from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PaperRecord:
    id: str
    title: str
    filename: str
    source_path: str
    storage_mode: str
    page_count: int
    created_at: str
    updated_at: str
    source_mtime: float
    source_size: int
    cache_state: str = "missing"
    guide_state: str = "missing"
    library_root: str = ""
    library_relpath: str = ""

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "PaperRecord":
        return cls(
            id=str(payload.get("id") or ""),
            title=str(payload.get("title") or "Untitled"),
            filename=str(payload.get("filename") or "paper.pdf"),
            source_path=str(payload.get("source_path") or ""),
            storage_mode=str(payload.get("storage_mode") or "linked"),
            page_count=int(payload.get("page_count") or 0),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            source_mtime=float(payload.get("source_mtime") or 0.0),
            source_size=int(payload.get("source_size") or 0),
            cache_state=str(payload.get("cache_state") or "missing"),
            guide_state=str(payload.get("guide_state") or "missing"),
            library_root=str(payload.get("library_root") or ""),
            library_relpath=str(payload.get("library_relpath") or ""),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "filename": self.filename,
            "source_path": self.source_path,
            "storage_mode": self.storage_mode,
            "page_count": self.page_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source_mtime": self.source_mtime,
            "source_size": self.source_size,
            "cache_state": self.cache_state,
            "guide_state": self.guide_state,
            "library_root": self.library_root,
            "library_relpath": self.library_relpath,
        }
