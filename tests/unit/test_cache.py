from pathlib import Path

import platformdirs
import pytest

from monitor_shift.runner.cache import cache_dir

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_env_override_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MSHIFT_CACHE_DIR", str(tmp_path / "store"))
    assert cache_dir() == tmp_path / "store"


def test_override_expands_the_home_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MSHIFT_CACHE_DIR", "~/mshift-cache")
    assert cache_dir() == Path.home() / "mshift-cache"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_default_is_the_platform_cache_outside_the_repo(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("MSHIFT_CACHE_DIR", raising=False)
    else:
        monkeypatch.setenv("MSHIFT_CACHE_DIR", value)
    path = cache_dir()
    assert path == platformdirs.user_cache_path("monitor-shift")
    assert REPO_ROOT not in path.resolve().parents
