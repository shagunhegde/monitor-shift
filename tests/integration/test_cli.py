from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from monitor_shift import __version__
from monitor_shift.cli import doctor
from monitor_shift.cli.doctor import Probes
from monitor_shift.cli.main import app

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


@pytest.fixture
def probes(tmp_path: Path) -> Probes:
    return Probes(
        env={"OPENAI_API_KEY": "sk-test"},
        hf_token=lambda: "hf_test",
        hf_access=lambda token: "ok",
        docker=lambda: "running",
        cache_dir=tmp_path / "cache",
        platform="darwin",
    )


def use_probes(monkeypatch: pytest.MonkeyPatch, probes: Probes) -> None:
    def default(cls: type[Probes]) -> Probes:
        return probes

    monkeypatch.setattr(doctor.Probes, "default", classmethod(default))


def test_no_arguments_prints_help() -> None:
    result = runner.invoke(app, [])
    assert "doctor" in result.output
    assert "demo" in result.output


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_doctor_passes_on_a_healthy_machine(
    monkeypatch: pytest.MonkeyPatch, probes: Probes
) -> None:
    use_probes(monkeypatch, probes)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "All checks passed" in result.output


def test_doctor_flags_each_problem_with_its_fix(
    monkeypatch: pytest.MonkeyPatch, probes: Probes
) -> None:
    broken = replace(probes, env={}, hf_token=lambda: None, docker=lambda: "stopped")
    use_probes(monkeypatch, broken)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "export OPENAI_API_KEY=" in result.output
    assert "hf auth login" in result.output
    assert "open -a Docker" in result.output


def test_doctor_offline_never_probes_the_hub(
    monkeypatch: pytest.MonkeyPatch, probes: Probes
) -> None:
    def explode(token: str | None) -> doctor.HubAccess:
        raise AssertionError("probed the Hub")

    use_probes(monkeypatch, replace(probes, hf_access=explode))
    result = runner.invoke(app, ["doctor", "--offline"])
    assert result.exit_code == 0, result.output


def test_demo_fake_runs_end_to_end() -> None:
    result = runner.invoke(app, ["demo", "--fake", "--scale", "0.1"])
    assert result.exit_code == 0, result.output
    for text in ("fake-basic", "fake-hybrid", "fake-constitutional", "L3", "achieved"):
        assert text in result.output


def test_demo_without_fake_explains_itself() -> None:
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 2
    assert "mshift demo --fake" in result.output


@pytest.mark.parametrize("scale", ["0", "-1", "11"])
def test_demo_rejects_silly_scales(scale: str) -> None:
    result = runner.invoke(app, ["demo", "--fake", "--scale", scale])
    assert result.exit_code == 2
