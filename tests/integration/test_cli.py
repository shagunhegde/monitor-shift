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


# --- Live commands, run offline against the mshift-fake model --------------------------------


def save_fixture_sets() -> None:
    from monitor_shift.adapters.fixtures import FixtureSource
    from monitor_shift.runner.store import save_trajectories

    save_trajectories("l0h", FixtureSource("L0", "honest", split="calibration").load(n=8, seed=1))
    save_trajectories("l0a", FixtureSource("L0", "attack").load(n=8, seed=1))
    save_trajectories("l2", FixtureSource("L2", "unknown").load(n=4, seed=1))


def test_score_then_spike_report_end_to_end(tmp_path: Path) -> None:
    save_fixture_sets()
    scored = runner.invoke(
        app,
        [
            "score", "--source", "l0h,l0a,l2", "--monitors", "basic,hybrid",
            "--model", "mshift-fake/scorer", "--samples", "1", "--max-usd", "1", "--run", "spk",
        ],
    )  # fmt: skip
    assert scored.exit_code == 0, scored.output
    assert "Scored into run spk" in scored.output
    report_path = tmp_path / "m1.md"
    report = runner.invoke(app, ["spike", "--run", "spk", "--write", str(report_path)])
    assert report.exit_code == 0, report.output
    text = report_path.read_text()
    assert "## Go / no-go" in text
    assert "| L0 | basic | 16 |" in text
    assert "Not yet scored: L1, L3" in text


def test_score_needs_a_model() -> None:
    save_fixture_sets()
    result = runner.invoke(app, ["score", "--source", "l2", "--max-usd", "1"])
    assert result.exit_code == 2
    assert "MSHIFT_MODEL" in result.output


def test_score_explains_a_missing_set() -> None:
    result = runner.invoke(
        app, ["score", "--source", "nope", "--model", "mshift-fake/scorer", "--max-usd", "1"]
    )
    assert result.exit_code == 2
    assert "mshift fetch" in result.output


def test_score_stops_at_the_cap_and_says_how_to_resume() -> None:
    save_fixture_sets()
    result = runner.invoke(
        app,
        [
            "score", "--source", "l0h,l0a", "--monitors", "basic", "--model", "mshift-fake/scorer",
            "--samples", "1", "--max-usd", "0.01", "--max-tokens-out", "200", "--concurrency", "1",
        ],
    )  # fmt: skip
    assert result.exit_code == 2
    assert "Stopped before exceeding --max-usd" in result.output
    assert "rerun the same command" in result.output


def test_aivillage_fetch_points_at_the_access_request() -> None:
    result = runner.invoke(app, ["fetch", "aivillage", "--n", "5"])
    assert result.exit_code == 2
    assert "huggingface.co/datasets/aidigestorg/ai-village" in result.output


def test_doctor_checks_the_default_model_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, probes: Probes
) -> None:
    use_probes(monkeypatch, probes)  # probes have only OPENAI_API_KEY
    monkeypatch.setenv("MSHIFT_MODEL", "openrouter/openai/gpt-6-luna")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "OPENROUTER_API_KEY" in result.output
