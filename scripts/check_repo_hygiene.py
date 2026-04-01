from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
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


def main() -> int:
    tracked = git_ls_files()
    violations: list[str] = []

    for path in tracked:
        normalized = path.as_posix()

        if normalized in BLOCKED_NAMES:
            violations.append(f"Temporary file is tracked: {normalized}")
            continue

        if normalized.startswith(BLOCKED_PREFIXES):
            if normalized.endswith(".gitkeep"):
                continue
            violations.append(f"Paper artifact is tracked: {normalized}")
            continue

        if normalized.endswith(BLOCKED_SUFFIXES):
            violations.append(f"Document file is tracked: {normalized}")

    if violations:
        print("Repository hygiene check failed:\n")
        for item in violations:
            print(f"- {item}")
        print(
            "\nKeep paper content and local caches outside git-tracked files before publishing this repository."
        )
        return 1

    print("Repository hygiene check passed.")
    return 0


def git_ls_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return [Path(line.strip()) for line in completed.stdout.splitlines() if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
