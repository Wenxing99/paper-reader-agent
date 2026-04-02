from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

from PIL import Image
from pypdf import PdfWriter


REPO_ROOT = Path(__file__).resolve().parent
if REPO_ROOT.name == "tests":
    REPO_ROOT = REPO_ROOT.parent
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from paper_reader_agent.config import AppConfig
from paper_reader_agent.models import PaperRecord
from paper_reader_agent.services.library import inspect_pdf, save_paper
from paper_reader_agent.services.papers import ensure_page_cache, ensure_text_cache, load_page, render_page_image
from paper_reader_agent.services.selection_regions import build_selection_debug_crop
from paper_reader_agent.services.storage import ensure_repo_dirs, metadata_path, read_json, selection_debug_image_path


class PdfStackTests(unittest.TestCase):
    def test_blank_pdf_can_be_inspected_cached_on_demand_and_rendered(self) -> None:
        repo_root = REPO_ROOT / ".tmp" / "test_pdf_stack_workspace"
        if repo_root.exists():
            shutil.rmtree(repo_root)
        repo_root.mkdir(parents=True, exist_ok=True)
        pdf_path = repo_root / "blank.pdf"

        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.add_blank_page(width=612, height=792)
        writer.add_blank_page(width=612, height=792)
        with pdf_path.open("wb") as handle:
            writer.write(handle)

        title, page_count = inspect_pdf(pdf_path)
        self.assertEqual(title, "")
        self.assertEqual(page_count, 3)

        config = AppConfig(
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
        ensure_repo_dirs(config)

        stat = pdf_path.stat()
        record = PaperRecord(
            id="blankpaper01",
            title="Blank",
            filename="blank.pdf",
            source_path=str(pdf_path.resolve()),
            storage_mode="linked",
            page_count=0,
            created_at="2026-04-01T00:00:00+00:00",
            updated_at="2026-04-01T00:00:00+00:00",
            source_mtime=stat.st_mtime,
            source_size=stat.st_size,
        )

        partial_record, first_page = ensure_page_cache(config, record, 1)
        self.assertEqual(partial_record.page_count, 3)
        self.assertEqual(partial_record.cache_state, "partial")
        self.assertAlmostEqual(float(first_page["width"]), 612.0)
        self.assertAlmostEqual(float(first_page["height"]), 792.0)
        self.assertFalse(first_page["has_text_layer"])
        self.assertEqual(first_page["text"], "")

        updated = ensure_text_cache(config, partial_record)
        self.assertEqual(updated.page_count, 3)
        self.assertEqual(updated.cache_state, "ready")

        page = load_page(config, updated.id, 2)
        self.assertAlmostEqual(float(page["width"]), 612.0)
        self.assertAlmostEqual(float(page["height"]), 792.0)
        self.assertFalse(page["has_text_layer"])
        self.assertEqual(page["text"], "")

        image_path = render_page_image(config, updated, 3)
        self.assertTrue(image_path.exists())
        self.assertEqual(image_path.suffix.lower(), ".png")


    def test_cache_warmup_does_not_overwrite_running_guide_state(self) -> None:
        repo_root = REPO_ROOT / ".tmp" / "test_pdf_stack_preserve_guide_state"
        if repo_root.exists():
            shutil.rmtree(repo_root)
        repo_root.mkdir(parents=True, exist_ok=True)
        pdf_path = repo_root / "blank.pdf"

        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with pdf_path.open("wb") as handle:
            writer.write(handle)

        config = AppConfig(
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
        ensure_repo_dirs(config)

        stat = pdf_path.stat()
        stale_record = PaperRecord(
            id="preserve01",
            title="Blank",
            filename="blank.pdf",
            source_path=str(pdf_path.resolve()),
            storage_mode="linked",
            page_count=0,
            created_at="2026-04-01T00:00:00+00:00",
            updated_at="2026-04-01T00:00:00+00:00",
            source_mtime=stat.st_mtime,
            source_size=stat.st_size,
            cache_state="warming",
            guide_state="missing",
        )
        save_paper(config, stale_record)

        running_record = PaperRecord.from_json(stale_record.to_json())
        running_record.guide_state = "running"
        running_record.updated_at = "2026-04-01T00:00:05+00:00"
        save_paper(config, running_record)

        updated = ensure_text_cache(config, stale_record)
        self.assertEqual(updated.cache_state, "ready")

        saved_payload = read_json(metadata_path(config, stale_record.id), {})
        self.assertEqual(saved_payload.get("guide_state"), "running")
        self.assertEqual(saved_payload.get("cache_state"), "ready")


    def test_selection_debug_crop_is_generated_from_selection_bounds(self) -> None:
        repo_root = REPO_ROOT / ".tmp" / "test_pdf_stack_selection_debug_crop"
        if repo_root.exists():
            shutil.rmtree(repo_root)
        repo_root.mkdir(parents=True, exist_ok=True)
        pdf_path = repo_root / "blank.pdf"

        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with pdf_path.open("wb") as handle:
            writer.write(handle)

        config = AppConfig(
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
        ensure_repo_dirs(config)

        stat = pdf_path.stat()
        record = PaperRecord(
            id="selection01",
            title="Blank",
            filename="blank.pdf",
            source_path=str(pdf_path.resolve()),
            storage_mode="linked",
            page_count=0,
            created_at="2026-04-01T00:00:00+00:00",
            updated_at="2026-04-01T00:00:00+00:00",
            source_mtime=stat.st_mtime,
            source_size=stat.st_size,
        )

        record, page = ensure_page_cache(config, record, 1)
        crop_payload = build_selection_debug_crop(
            config,
            record,
            page,
            {
                "page_number": 1,
                "bounds": {"x": 100, "y": 120, "width": 80, "height": 60},
                "rects": [{"x": 100, "y": 120, "width": 80, "height": 60}],
            },
        )

        image_path = selection_debug_image_path(config, record.id, crop_payload["crop_id"])
        self.assertTrue(image_path.exists())
        with Image.open(image_path) as image:
            self.assertGreater(image.width, 0)
            self.assertGreater(image.height, 0)
            self.assertGreaterEqual(image.width, 100)
            self.assertGreaterEqual(image.height, 80)


if __name__ == "__main__":
    unittest.main()



