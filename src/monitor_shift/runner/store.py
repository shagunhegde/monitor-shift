"""The local store, under the cache directory and never in the repo.

M1 keeps it simple: JSON Lines files, one per named trajectory set and per scoring run, plus
runs.jsonl recording each live command's config, versions and spend. M2 moves scores to the
parquet store keyed by (trajectory hash, monitor, model, prompt hash, seed).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from monitor_shift.errors import ConfigError
from monitor_shift.runner.cache import cache_dir
from monitor_shift.runner.score import ComponentResult, MonitorResult
from monitor_shift.runner.truncate import TruncationReport
from monitor_shift.schema import Trajectory

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _check_name(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise ConfigError(
            f"{name!r} isn't a valid set name.",
            hint="Use letters, digits, '.', '_' and '-', e.g. L0-agentdojo-honest-s7",
        )
    return name


def _write_atomic(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")
    Path(tmp).replace(path)


def trajectories_path(name: str) -> Path:
    return cache_dir() / "trajectories" / f"{_check_name(name)}.jsonl"


def save_trajectories(name: str, trajectories: Iterable[Trajectory]) -> Path:
    path = trajectories_path(name)
    _write_atomic(path, (json.dumps(t.to_dict(), ensure_ascii=False) for t in trajectories))
    return path


def load_trajectories(name: str) -> list[Trajectory]:
    path = trajectories_path(name)
    if not path.exists():
        known = sorted(p.stem for p in path.parent.glob("*.jsonl")) if path.parent.exists() else []
        raise ConfigError(
            f"No trajectory set named {name!r} in {path.parent}.",
            hint=(
                f"Known sets: {', '.join(known)}"
                if known
                else "Create one with `mshift fetch` or `mshift generate`."
            ),
        )
    with path.open(encoding="utf-8") as handle:
        return [Trajectory.from_dict(json.loads(line)) for line in handle if line.strip()]


def results_path(name: str) -> Path:
    return cache_dir() / "scores" / f"{_check_name(name)}.jsonl"


def append_results(name: str, results: Iterable[MonitorResult]) -> Path:
    path = results_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
    return path


def result_from_dict(data: Mapping[str, Any]) -> MonitorResult:
    fields = dict(data)
    fields["truncation"] = TruncationReport(**fields["truncation"])
    fields["components"] = tuple(ComponentResult(**c) for c in fields["components"])
    fields["weights"] = tuple(fields["weights"])
    return MonitorResult(**fields)


def load_results(name: str) -> list[MonitorResult]:
    path = results_path(name)
    if not path.exists():
        raise ConfigError(f"No scoring run named {name!r}.", hint="Run `mshift score` first.")
    with path.open(encoding="utf-8") as handle:
        rows = [result_from_dict(json.loads(line)) for line in handle if line.strip()]
    # A resumed run appends; keep the latest result per (trajectory, monitor, prompt).
    latest = {(r.trajectory_id, r.monitor, r.model, r.prompt_hash): r for r in rows}
    return list(latest.values())


def log_run(record: Mapping[str, Any]) -> None:
    entry = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "versions": {p: version(p) for p in ("monitor-shift", "control-arena", "inspect-ai")},
        **record,
    }
    path = cache_dir() / "runs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
