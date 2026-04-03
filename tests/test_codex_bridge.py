from __future__ import annotations

import base64
import importlib.util
import shutil
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
if REPO_ROOT.name == "tests":
    REPO_ROOT = REPO_ROOT.parent

BRIDGE_PATH = REPO_ROOT / "scripts" / "codex_bridge.py"
spec = importlib.util.spec_from_file_location("paper_reader_codex_bridge", BRIDGE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def make_workspace_tmpdir() -> Path:
    parent = REPO_ROOT / "scripts" / ".codex-bridge-workdir" / "test-workdirs"
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


class CodexBridgeImageTests(unittest.TestCase):
    def test_build_prompt_materializes_first_message_image(self) -> None:
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0xkAAAAASUVORK5CYII="
        )
        data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")

        tmpdir = make_workspace_tmpdir()
        try:
            prompt, image_paths = module.build_prompt(
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Recover this formula."},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
                workdir=tmpdir,
            )

            self.assertIn("Recover this formula.", prompt)
            self.assertEqual(len(image_paths), 1)
            self.assertTrue(Path(image_paths[0]).exists())
            self.assertEqual(Path(image_paths[0]).suffix.lower(), ".png")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_build_prompt_rejects_images_outside_first_message(self) -> None:
        tmpdir = make_workspace_tmpdir()
        try:
            with self.assertRaises(module.BridgeError):
                module.build_prompt(
                    [
                        {"role": "system", "content": "Context first."},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Use this image."},
                                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
                            ],
                        },
                    ],
                    workdir=tmpdir,
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
