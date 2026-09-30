"""Where the local store lives. The parquet store itself arrives in milestone M2."""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs


def cache_dir() -> Path:
    """$MSHIFT_CACHE_DIR if set, else the platform cache dir. Never inside the repo."""
    override = os.environ.get("MSHIFT_CACHE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return platformdirs.user_cache_path("monitor-shift")
