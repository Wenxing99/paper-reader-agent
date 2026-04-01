from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
BLOCKED_PREFIXES = (
    "data/papers/",
    "data/exports/",
)
BLOCKED_SUFFIXES = (
    ".pdf",
    ".epub",
)
BLOCKED_NAMES = (
    "app_css_resize_edit_tmp.css",
    "app_js_resize_edit_tmp.js",
    "index_resize_edit_tmp.html",
)
TEXT_SCAN_SUFFIXES = {
    ".md",
    ".py",
    ".js",
    ".css",
    ".html",
    ".cmd",
    ".txt",
    ".json",
    ".toml",
    ".yml",
    ".yaml",
}
TEXT_SCAN_EXCLUDED_PREFIXES = (
    ".venv/",
    ".tmp/",
    "data/papers/",
    "data/exports/",
    "src/paper_reader_agent/static/vendor/",
)
TEXT_SCAN_EXCLUDED_FILES = {
    "scripts/check_repo_hygiene.py",
}
PLACEHOLDER_PATTERN = re.compile(r"\?{3,}")


def _chars(*values: int) -> str:
    return "".join(chr(value) for value in values)


MOJIBAKE_MARKERS = (
    _chars(0x00C3, 0x00A9),
    _chars(0x00C3, 0x00A8),
    _chars(0x00C3, 0x00B6),
    _chars(0x00C3, 0x00BC),
    _chars(0x00C3, 0x00B1),
    _chars(0x00E2, 0x20AC, 0x201D),
    _chars(0x00E2, 0x20AC, 0x201C),
    _chars(0x00E2, 0x20AC, 0x02DC),
    _chars(0x00E2, 0x20AC, 0x2122),
    _chars(0x00E2, 0x20AC, 0x00A6),
    _chars(0x00EF, 0x00BC),
    _chars(0x00E3, 0x20AC),
    _chars(0x00E6, 0x02DC),
    _chars(0x00E6, 0x0153),
    _chars(0x00E4, 0x00B8),
    _chars(0x00E5, 0x00BD),
    _chars(0x00E7, 0x0161),
    _chars(0x00E8, 0x00AF),
    _chars(0x00E5, 0x00B7),
    _chars(0x00E5, 0x2026),
    _chars(0xFFFD),
)


def main() -> int:
    candidates = repo_candidate_files()
    violations: list[str] = []

    for path in candidates:
        normalized = path.as_posix()

        if normalized in BLOCKED_NAMES:
            violations.append(f"Temporary file is present: {normalized}")
            continue

        if normalized.startswith(BLOCKED_PREFIXES):
            if normalized.endswith(".gitkeep"):
                continue
            violations.append(f"Paper artifact is present: {normalized}")
            continue

        if normalized.endswith(BLOCKED_SUFFIXES):
            violations.append(f"Document file is present: {normalized}")

        violations.extend(scan_text_integrity(path))

    if violations:
        print("Repository hygiene check failed:\n")
        for item in violations:
            print(f"- {item}")
        print(
            "\nKeep paper content and corrupted text out of repository files before publishing this project."
        )
        return 1

    print("Repository hygiene check passed.")
    return 0


def repo_candidate_files() -> list[Path]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "ls-files",
            "-z",
            "--cached",
            "--modified",
            "--others",
            "--exclude-standard",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    paths = [Path(item) for item in completed.stdout.split("\0") if item]
    return list(dict.fromkeys(paths))


def scan_text_integrity(path: Path) -> list[str]:
    normalized = path.as_posix()
    if normalized in TEXT_SCAN_EXCLUDED_FILES:
        return []
    if path.suffix.lower() not in TEXT_SCAN_SUFFIXES:
        return []
    if normalized.startswith(TEXT_SCAN_EXCLUDED_PREFIXES):
        return []

    try:
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        return [f"UTF-8 decode failed for {normalized}: {error}"]

    violations: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        preview = line.strip()[:120].encode("unicode_escape").decode("ascii")
        if PLACEHOLDER_PATTERN.search(line):
            violations.append(
                f"Suspicious placeholder in {normalized}:{line_number}: {preview}"
            )
        if any(marker in line for marker in MOJIBAKE_MARKERS):
            violations.append(
                f"Possible mojibake in {normalized}:{line_number}: {preview}"
            )
    return violations


if __name__ == "__main__":
    raise SystemExit(main())
