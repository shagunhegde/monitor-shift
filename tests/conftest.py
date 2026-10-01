"""Shared test setup: every test runs offline against a throwaway cache."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hypothesis import settings

settings.register_profile("default", deadline=None, max_examples=200)
settings.register_profile("ci", deadline=None, max_examples=500)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the cache at a temp dir and make Hugging Face refuse to download."""
    monkeypatch.setenv("MSHIFT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("HF_DATASETS_OFFLINE", "1")
