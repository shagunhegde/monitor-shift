"""monitor-shift: how synthetic-calibrated agent monitor thresholds behave on real agent logs."""

from importlib.metadata import version

from monitor_shift.errors import ConfigError, MonitorShiftError, SchemaError
from monitor_shift.schema import MonitorSpec, Score, Source, Step, Trajectory

__version__ = version("monitor-shift")

__all__ = [
    "ConfigError",
    "MonitorShiftError",
    "MonitorSpec",
    "SchemaError",
    "Score",
    "Source",
    "Step",
    "Trajectory",
    "__version__",
]
