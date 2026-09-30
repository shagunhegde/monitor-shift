import pytest

from monitor_shift import errors
from monitor_shift.errors import MonitorShiftError


def _all_error_classes() -> list[type[MonitorShiftError]]:
    found: list[type[MonitorShiftError]] = [MonitorShiftError]
    for cls in found:
        found.extend(cls.__subclasses__())
    return found


def test_error_module_exports_subclasses() -> None:
    names = {cls.__name__ for cls in _all_error_classes()}
    assert {"MonitorShiftError", "SchemaError", "ConfigError"} <= names
    assert all(hasattr(errors, name) for name in names)


@pytest.mark.parametrize("cls", _all_error_classes())
def test_every_error_class_requires_a_hint(cls: type[MonitorShiftError]) -> None:
    with pytest.raises(ValueError, match="hint"):
        cls("something broke", hint="   ")


@pytest.mark.parametrize("cls", _all_error_classes())
def test_error_text_carries_message_and_hint(cls: type[MonitorShiftError]) -> None:
    err = cls("the cache is read-only", hint="export MSHIFT_CACHE_DIR=/tmp/mshift")
    assert err.message == "the cache is read-only"
    assert err.hint == "export MSHIFT_CACHE_DIR=/tmp/mshift"
    assert "the cache is read-only" in str(err)
    assert "Fix: export MSHIFT_CACHE_DIR=/tmp/mshift" in str(err)
