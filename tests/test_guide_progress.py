from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
if REPO_ROOT.name == "tests":
    REPO_ROOT = REPO_ROOT.parent
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from paper_reader_agent.config import AppConfig
from paper_reader_agent.models import PaperRecord
from paper_reader_agent.services.guide_jobs import get_reading_guide_status, queue_reading_guide_generation
from paper_reader_agent.services.library import save_paper
from paper_reader_agent.services.storage import ensure_repo_dirs, guide_path, guide_status_path, write_json


class GuideProgressTests(unittest.TestCase):
    def make_config(self, name: str) -> AppConfig:
        repo_root = REPO_ROOT / ".tmp" / name
        if repo_root.exists():
            shutil.rmtree(repo_root)
        repo_root.mkdir(parents=True, exist_ok=True)
        return AppConfig(
            repo_root=repo_root,
            data_root=repo_root / "data",
            papers_root=repo_root / "data" / "papers",
            exports_root=repo_root / "data" / "exports",
            obsidian_root=repo_root / "data" / "exports" / "obsidian",
            bridge_url="http://127.0.0.1:8765/v1",
            model="gpt-5.4",
            api_key="",
            reasoning_effort="",
            host="127.0.0.1",
            port=8790,
            max_guide_chars=1000,
            max_context_pages=4,
            max_page_context_chars=1000,
            render_scale=1.5,
        )

    def make_record(self, guide_state: str) -> PaperRecord:
        return PaperRecord(
            id="guidepaper01",
            title="Guide Paper",
            filename="guide.pdf",
            source_path=str((REPO_ROOT / ".tmp" / "guide-placeholder.pdf").resolve()),
            storage_mode="linked",
            page_count=3,
            created_at="2026-04-02T00:00:00+00:00",
            updated_at="2026-04-02T00:00:00+00:00",
            source_mtime=0.0,
            source_size=0,
            cache_state="ready",
            guide_state=guide_state,
        )

    def test_running_status_marks_current_stage(self) -> None:
        config = self.make_config("test_guide_progress_running")
        ensure_repo_dirs(config)
        record = self.make_record("running")
        save_paper(config, record)
        write_json(
            guide_status_path(config, record.id),
            {
                "state": "running",
                "stage": "draft_guide",
                "updated_at": "2026-04-02T01:00:00+00:00",
            },
        )

        status = get_reading_guide_status(config, record)
        self.assertEqual(status["state"], "running")
        self.assertEqual(status["stage"], "draft_guide")
        self.assertEqual(status["steps"][2]["state"], "current")
        self.assertEqual(status["steps"][0]["state"], "complete")

    def test_ready_guide_is_reused_without_queueing_background_job(self) -> None:
        config = self.make_config("test_guide_progress_ready")
        ensure_repo_dirs(config)
        record = self.make_record("ready")
        save_paper(config, record)
        guide_payload = {
            "paper_title": "Guide Paper",
            "one_sentence": "One sentence summary.",
            "background": [],
            "problem": [],
            "innovations": [],
            "method": [],
            "results": [],
            "limitations": [],
            "reading_guide": [],
            "sections": [],
            "model": "gpt-5.4",
        }
        write_json(guide_path(config, record.id), guide_payload)

        returned_record, status, guide = queue_reading_guide_generation(config, {"model": "gpt-5.4"}, record)
        self.assertEqual(returned_record.id, record.id)
        self.assertEqual(status["state"], "ready")
        self.assertEqual(guide, guide_payload)


if __name__ == "__main__":
    unittest.main()
