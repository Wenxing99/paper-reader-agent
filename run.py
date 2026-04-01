from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from paper_reader_agent.app import create_app
from paper_reader_agent.config import load_config


app = create_app()


if __name__ == "__main__":
    config = load_config()
    app.run(host=config.host, port=config.port, debug=False)
