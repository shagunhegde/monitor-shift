"""The one trajectory format every source is converted into, plus monitor specs and scores."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Protocol, cast, get_args

from monitor_shift.errors import SchemaError

# Bump when the hashed payload changes: every cached score is keyed on this hash.
SCHEMA_VERSION = "trajectory/v1"

SourceName = Literal["controlarena", "swe_agent", "aivillage", "fixture"]
Rung = Literal["L0", "L1", "L2", "L3"]
Label = Literal["honest", "attack", "unknown"]
Unit = Literal["trajectory", "step"]

_ADAPTER_HINT = (
    "This is a bug in the adapter that built it; fix the adapter and re-run `mshift fetch`."
)


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_content_hash(task: str, steps: Sequence[Step]) -> str:
    """Hash exactly what a monitor sees: the task and the steps, not ids, labels or meta.

    Fields are JSON-encoded so text can't shift between fields without changing the hash.
    """
    rows = [[s.index, s.action, s.observation, s.message, s.timestamp] for s in steps]
    payload = json.dumps([SCHEMA_VERSION, task, rows], ensure_ascii=False, separators=(",", ":"))
    return hash_text(payload)


def _check_choice(name: str, value: object, allowed: Any) -> None:
    choices: tuple[str, ...] = get_args(allowed)
    if value not in choices:
        raise SchemaError(
            f"{name}={value!r} is not one of {', '.join(choices)}.", hint=_ADAPTER_HINT
        )


@dataclass(frozen=True)
class Step:
    index: int
    action: str  # tool call or command, rendered as text
    observation: str | None = None  # tool output, truncated by runner/truncate.py
    message: str | None = None  # agent message or reasoning, if the source has one
    timestamp: str | None = None

    def __post_init__(self) -> None:
        if self.index < 0:
            raise SchemaError(f"Step index {self.index} is negative.", hint=_ADAPTER_HINT)
        if not self.action.strip() and not (self.message or "").strip():
            raise SchemaError(
                f"Step {self.index} has neither an action nor a message, "
                "so a monitor would have nothing to read.",
                hint="Drop empty turns in the adapter before building Steps.",
            )


@dataclass(frozen=True)
class Trajectory:
    id: str  # source-native: session id, SWE instance + model, ControlArena sample id
    source: SourceName
    rung: Rung
    task: str  # the task or session goal shown to the monitor
    steps: tuple[Step, ...]
    label: Label
    meta: Mapping[str, str] = field(default_factory=dict[str, str])  # agent, model, month, split
    content_hash: str = ""  # computed when empty, verified when given

    def __post_init__(self) -> None:
        _check_choice("source", self.source, SourceName)
        _check_choice("rung", self.rung, Rung)
        _check_choice("label", self.label, Label)
        if not self.id.strip():
            raise SchemaError("A trajectory has an empty id.", hint=_ADAPTER_HINT)
        if not self.task.strip():
            raise SchemaError(
                f"Trajectory {self.id} has an empty task, so a monitor can't judge intent.",
                hint=_ADAPTER_HINT,
            )
        steps = tuple(self.steps)
        if not steps:
            raise SchemaError(f"Trajectory {self.id} has no steps.", hint=_ADAPTER_HINT)
        for expected, step in enumerate(steps):
            if step.index != expected:
                raise SchemaError(
                    f"Trajectory {self.id}: step {expected} has index {step.index}; "
                    "steps must be numbered 0, 1, 2, ... in order.",
                    hint=_ADAPTER_HINT,
                )
        meta = dict(self.meta)
        bad = {k: v for k, v in meta.items() if not isinstance(v, str)}  # pyright: ignore[reportUnnecessaryIsInstance]
        if bad:
            raise SchemaError(
                f"Trajectory {self.id}: meta values must be strings, got {bad!r}.",
                hint=_ADAPTER_HINT,
            )
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "meta", MappingProxyType(meta))

        digest = compute_content_hash(self.task, steps)
        if not self.content_hash:
            object.__setattr__(self, "content_hash", digest)
        elif self.content_hash != digest:
            raise SchemaError(
                f"Trajectory {self.id}: stored content_hash {self.content_hash[:12]}... does not "
                f"match its content ({digest[:12]}...). The task or steps changed after hashing.",
                hint="Rebuild it with content_hash='' (e.g. dataclasses.replace(t, ..., "
                "content_hash='')), or re-run `mshift fetch` to refresh the cache.",
            )

    def __hash__(self) -> int:
        return hash((self.id, self.content_hash))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "id": self.id,
            "source": self.source,
            "rung": self.rung,
            "task": self.task,
            "steps": [asdict(step) for step in self.steps],
            "label": self.label,
            "meta": dict(self.meta),
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Trajectory:
        if data.get("schema") != SCHEMA_VERSION:
            raise SchemaError(
                f"Stored trajectory uses schema {data.get('schema')!r}, "
                f"this version reads {SCHEMA_VERSION!r}.",
                hint="Re-run `mshift fetch` to rebuild the cache with this version.",
            )
        steps = cast(list[dict[str, Any]], data["steps"])
        return cls(
            id=data["id"],
            source=data["source"],
            rung=data["rung"],
            task=data["task"],
            steps=tuple(Step(**step) for step in steps),
            label=data["label"],
            meta=data["meta"],
            content_hash=data["content_hash"],
        )


@dataclass(frozen=True)
class MonitorSpec:
    name: str  # "basic", "hybrid", "constitutional"
    unit: Unit
    prompt_hash: str  # ControlArena built-in or a prompt file, hashed
    model: str
    samples: int = 3  # >1 uses ensemble_monitor_builder to break ties (Lite scope: 3)
    max_tokens_in: int = 24_000

    def __post_init__(self) -> None:
        _check_choice("unit", self.unit, Unit)
        hint = "Fix the monitor definition in your config (configs/study.yaml)."
        if not self.name.strip() or not self.model.strip():
            raise SchemaError("A monitor spec needs a name and a model.", hint=hint)
        if self.samples < 1:
            raise SchemaError(f"samples={self.samples}; need at least 1.", hint=hint)
        if self.max_tokens_in < 1:
            raise SchemaError(f"max_tokens_in={self.max_tokens_in}; need at least 1.", hint=hint)


@dataclass(frozen=True)
class Score:
    trajectory_id: str
    step_index: int | None  # None for trajectory-level monitors
    monitor: str
    raw: float
    normalized: float  # ControlArena's [0, 1]
    reason: str
    cost_usd: float = 0.0
    cached: bool = False

    def __post_init__(self) -> None:
        hint = "The monitor returned an unusable score; check its score parsing."
        if not math.isfinite(self.raw):
            raise SchemaError(f"{self.monitor}: raw score {self.raw} is not finite.", hint=hint)
        if not 0.0 <= self.normalized <= 1.0:  # also rejects NaN
            raise SchemaError(
                f"{self.monitor}: normalized score {self.normalized} is outside [0, 1].",
                hint=hint,
            )
        if not self.cost_usd >= 0.0:
            raise SchemaError(f"{self.monitor}: negative cost {self.cost_usd}.", hint=hint)
        if self.step_index is not None and self.step_index < 0:
            raise SchemaError(f"{self.monitor}: negative step index.", hint=hint)


class Source(Protocol):
    def load(self, n: int, seed: int, stratify: Sequence[str] = ()) -> Sequence[Trajectory]: ...

    def fingerprint(self) -> str: ...
