from __future__ import annotations

import base64
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parent
if REPO_ROOT.name == "tests":
    REPO_ROOT = REPO_ROOT.parent
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from paper_reader_agent.config import AppConfig
from paper_reader_agent.models import PaperRecord
import paper_reader_agent.app as app_module


class SelectionActionRouteTests(unittest.TestCase):
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

    def make_record(self) -> PaperRecord:
        return PaperRecord(
            id="paper001",
            title="Formula Paper",
            filename="paper.pdf",
            source_path=str((REPO_ROOT / ".tmp" / "selection-route-paper.pdf").resolve()),
            storage_mode="linked",
            page_count=12,
            created_at="2026-04-03T00:00:00+00:00",
            updated_at="2026-04-03T00:00:00+00:00",
            source_mtime=0.0,
            source_size=0,
            cache_state="ready",
            guide_state="ready",
        )

    def make_crop_path(self, config: AppConfig) -> Path:
        crop_path = config.repo_root / "crop.png"
        crop_path.write_bytes(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0xkAAAAASUVORK5CYII="
            )
        )
        return crop_path

    def make_client(self, config: AppConfig):
        with mock.patch.object(app_module, "load_config", return_value=config):
            flask_app = app_module.create_app()
        flask_app.config.update(TESTING=True)
        return flask_app.test_client()

    def test_math_heavy_selection_routes_through_stage_b_and_hides_internal_artifacts(self) -> None:
        config = self.make_config("test_selection_action_math_heavy")
        client = self.make_client(config)
        record = self.make_record()
        crop_path = self.make_crop_path(config)

        fallback_chat = mock.Mock(return_value="fallback answer")
        stage_a = {"latex": r"\alpha + \beta", "confidence": "high", "warnings": []}
        stage_b = mock.Mock(return_value="final math explanation")

        with (
            mock.patch.object(app_module, "get_paper", return_value=record),
            mock.patch.object(app_module, "ensure_text_cache", return_value=record),
            mock.patch.object(app_module, "load_reading_guide", return_value={}),
            mock.patch.object(app_module, "load_page", return_value={"page_number": 6}),
            mock.patch.object(app_module, "build_selection_context", return_value="paper context"),
            mock.patch.object(app_module, "should_use_formula_stage", return_value=True),
            mock.patch.object(app_module, "build_selection_debug_crop", return_value={"crop_id": "crop001"}),
            mock.patch.object(app_module, "selection_debug_image_path", return_value=crop_path),
            mock.patch.object(app_module, "request_formula_stage_a", return_value=stage_a),
            mock.patch.object(app_module, "request_formula_stage_b", stage_b),
            mock.patch.object(app_module, "request_chat_completion", fallback_chat),
        ):
            response = client.post(
                "/api/papers/paper001/selection-action",
                json={
                    "page": 6,
                    "mode": "explain",
                    "text": "Theorem 1: ||x-y|| <= C / sqrt(n)",
                    "selection_region": {"bounds": {"x": 10, "y": 20, "width": 30, "height": 40}},
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["text"], "final math explanation")
        self.assertNotIn("debug_crop", payload)
        self.assertNotIn("formula_stage_a", payload)
        stage_b.assert_called_once()
        fallback_chat.assert_not_called()

    def test_plain_selection_stays_on_text_only_path(self) -> None:
        config = self.make_config("test_selection_action_plain")
        client = self.make_client(config)
        record = self.make_record()
        fallback_chat = mock.Mock(return_value="plain explanation")

        with (
            mock.patch.object(app_module, "get_paper", return_value=record),
            mock.patch.object(app_module, "ensure_text_cache", return_value=record),
            mock.patch.object(app_module, "load_reading_guide", return_value={}),
            mock.patch.object(app_module, "load_page", return_value={"page_number": 2}),
            mock.patch.object(app_module, "build_selection_context", return_value="paper context"),
            mock.patch.object(app_module, "should_use_formula_stage", return_value=False),
            mock.patch.object(app_module, "request_formula_stage_a") as request_stage_a,
            mock.patch.object(app_module, "request_formula_stage_b") as request_stage_b,
            mock.patch.object(app_module, "build_selection_debug_crop") as build_crop,
            mock.patch.object(app_module, "request_chat_completion", fallback_chat),
        ):
            response = client.post(
                "/api/papers/paper001/selection-action",
                json={
                    "page": 2,
                    "mode": "explain",
                    "text": "This paragraph explains the motivation of the method.",
                    "selection_region": {"bounds": {"x": 10, "y": 20, "width": 30, "height": 40}},
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["text"], "plain explanation")
        request_stage_a.assert_not_called()
        request_stage_b.assert_not_called()
        build_crop.assert_not_called()
        fallback_chat.assert_called_once()


if __name__ == "__main__":
    unittest.main()
