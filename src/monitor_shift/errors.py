"""Error types. Each says what happened and why, and carries a `hint`: the exact fix."""

from __future__ import annotations


class MonitorShiftError(Exception):
    """Base class for every error monitor-shift raises on purpose."""

    def __init__(self, message: str, *, hint: str) -> None:
        if not hint.strip():
            raise ValueError(f"{type(self).__name__} needs a non-empty hint: {message!r}")
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.message}\nFix: {self.hint}"


class SchemaError(MonitorShiftError):
    """A trajectory, step, score or monitor spec is malformed."""


class ConfigError(MonitorShiftError):
    """A command or config asks for something monitor-shift can't do."""
