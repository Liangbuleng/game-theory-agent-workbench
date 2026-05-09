"""Small logging helpers for LLM diagnostics."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


def emit_log(message: str) -> None:
    """Print a diagnostic line and optionally append it to a log file."""

    print(message, flush=True)
    log_path = os.environ.get("GTA_LLM_LOG_FILE")
    if not log_path:
        return

    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} {message}\n")
