import subprocess
from dataclasses import replace
from pathlib import Path

import huggingface_hub
import pytest
import requests
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, RepositoryNotFoundError

from monitor_shift.cli import doctor
from monitor_shift.cli.doctor import (
    AIVILLAGE_URL,
    CheckResult,
    DockerState,
    HubAccess,
    Probes,
    check_aivillage,
    check_api_keys,
    check_cache,
    check_docker,
    exit_code,
    run_checks,
)


def healthy_probes(tmp_path: Path) -> Probes:
    return Probes(
        env={"OPENAI_API_KEY": "sk-test"},
        hf_token=lambda: "hf_test",
        hf_access=lambda token: "ok",
        docker=lambda: "running",
        cache_dir=tmp_path / "cache",
        platform="darwin",
    )


# --- API keys -------------------------------------------------------------------------------


def test_missing_api_key_fails_with_an_export_fix() -> None:
    result = check_api_keys(env={}, model=None)
    assert result.status == "fail"
    assert result.fix is not None
    assert "export OPENAI_API_KEY=" in result.fix


def test_any_provider_key_passes_without_a_model() -> None:
    result = check_api_keys(env={"ANTHROPIC_API_KEY": "x"}, model=None)
    assert result.status == "ok"
    assert "anthropic" in result.detail


def test_blank_keys_do_not_count() -> None:
    assert check_api_keys(env={"OPENAI_API_KEY": "  "}, model=None).status == "fail"


def test_model_checks_its_own_provider() -> None:
    result = check_api_keys(env={"OPENAI_API_KEY": "x"}, model="anthropic/claude-haiku-4-5")
    assert result.status == "fail"
    assert result.fix is not None
    assert "ANTHROPIC_API_KEY" in result.fix
    assert check_api_keys(env={"OPENAI_API_KEY": "x"}, model="openai/gpt-4.1-mini").status == "ok"


def test_model_can_come_from_the_environment() -> None:
    env = {"OPENAI_API_KEY": "x", "INSPECT_EVAL_MODEL": "google/gemini-2.5-flash"}
    result = check_api_keys(env=env, model=None)
    assert result.status == "fail"
    assert result.fix is not None
    assert "GOOGLE_API_KEY" in result.fix


def test_local_providers_need_no_key() -> None:
    assert check_api_keys(env={}, model="ollama/llama3").status == "ok"


def test_unknown_provider_warns() -> None:
    result = check_api_keys(env={}, model="acme/model-1")
    assert result.status == "warn"
    assert result.fix


# --- AI Village access ----------------------------------------------------------------------


def test_no_token_fails_with_a_login_fix() -> None:
    result = check_aivillage(token=None, access=lambda token: "ok", offline=False)
    assert result.status == "fail"
    assert result.fix is not None
    assert "hf auth login" in result.fix
    assert AIVILLAGE_URL in result.fix


def test_gated_access_fails_with_an_accept_terms_fix() -> None:
    result = check_aivillage(token="hf_x", access=lambda token: "gated", offline=False)
    assert result.status == "fail"
    assert result.fix is not None
    assert AIVILLAGE_URL in result.fix
    assert "mshift doctor" in result.fix


def test_rejected_token_fails_with_a_login_fix() -> None:
    result = check_aivillage(token="hf_x", access=lambda token: "unauthorized", offline=False)
    assert result.status == "fail"
    assert result.fix is not None
    assert "hf auth login" in result.fix


@pytest.mark.parametrize(("access", "status"), [("ok", "ok"), ("network", "warn")])
def test_access_outcomes(access: HubAccess, status: str) -> None:
    assert check_aivillage(token="hf_x", access=lambda t: access, offline=False).status == status


def test_offline_skips_the_network_probe() -> None:
    def explode(token: str | None) -> HubAccess:
        raise AssertionError("offline doctor must not probe the Hub")

    result = check_aivillage(token="hf_x", access=explode, offline=True)
    assert result.status == "warn"
    assert "offline" in result.detail


# --- Docker ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "fix"), [("darwin", "open -a Docker"), ("linux", "sudo systemctl start docker")]
)
def test_stopped_docker_daemon_is_flagged_with_a_start_fix(platform: str, fix: str) -> None:
    result = check_docker(lambda: "stopped", platform=platform)
    assert result.status == "warn"
    assert result.fix is not None
    assert fix in result.fix
    assert "BashArena" in result.detail


def test_missing_docker_cli_is_flagged_with_an_install_fix() -> None:
    result = check_docker(lambda: "missing", platform="linux")
    assert result.status == "warn"
    assert result.fix is not None
    assert "docs.docker.com" in result.fix


def test_running_docker_passes() -> None:
    assert check_docker(lambda: "running", platform="linux").status == "ok"


def test_docker_probe_classifies_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    def not_installed(name: str) -> None:
        return None

    monkeypatch.setattr(doctor.shutil, "which", not_installed)
    state: DockerState = doctor.probe_docker()
    assert state == "missing"


# --- Cache ----------------------------------------------------------------------------------


def test_writable_cache_passes_and_is_created(tmp_path: Path) -> None:
    result = check_cache(tmp_path / "new" / "cache")
    assert result.status == "ok"
    assert (tmp_path / "new" / "cache").is_dir()
    assert not list((tmp_path / "new" / "cache").iterdir())


def test_unusable_cache_fails_with_an_env_fix(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    result = check_cache(blocker)
    assert result.status == "fail"
    assert result.fix is not None
    assert "MSHIFT_CACHE_DIR" in result.fix


# --- Whole report ---------------------------------------------------------------------------


def test_healthy_machine_passes(tmp_path: Path) -> None:
    results = run_checks(healthy_probes(tmp_path), model=None, offline=False)
    assert [r.status for r in results] == ["ok"] * len(results)
    assert exit_code(results) == 0


def test_every_problem_is_reported_with_its_fix(tmp_path: Path) -> None:
    def gated(token: str | None) -> HubAccess:
        return "gated"

    broken = replace(healthy_probes(tmp_path), env={}, hf_access=gated, docker=lambda: "stopped")
    results = {r.name: r for r in run_checks(broken, model=None, offline=False)}
    assert results["API key"].status == "fail"
    assert results["AI Village access"].status == "fail"
    assert results["Docker"].status == "warn"
    assert all(r.fix for r in results.values() if r.status != "ok")
    assert exit_code(list(results.values())) == 1


def test_warnings_alone_do_not_fail() -> None:
    results = [CheckResult("x", "ok", "fine", None), CheckResult("y", "warn", "meh", "do it")]
    assert exit_code(results) == 0


# --- Real probes, with their I/O faked -----------------------------------------------------


def http_error(cls: type[HfHubHTTPError], status: int | None) -> HfHubHTTPError:
    if status is None:
        return cls("no response")
    response = requests.Response()
    response.status_code = status
    return cls(f"HTTP {status}", response=response)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (None, "ok"),
        (http_error(GatedRepoError, 403), "gated"),
        (http_error(RepositoryNotFoundError, 404), "not_found"),
        (http_error(HfHubHTTPError, 401), "unauthorized"),
        (http_error(HfHubHTTPError, 500), "network"),
        (http_error(HfHubHTTPError, None), "network"),
        (requests.ConnectionError("down"), "network"),
    ],
)
def test_hub_probe_classifies_responses(
    monkeypatch: pytest.MonkeyPatch, error: Exception | None, expected: HubAccess
) -> None:
    def fake_auth_check(
        repo_id: str, *, repo_type: str | None = None, token: str | bool | None = None
    ) -> None:
        assert repo_id == doctor.AIVILLAGE_REPO
        assert repo_type == "dataset"
        if error is not None:
            raise error

    monkeypatch.setattr(huggingface_hub, "auth_check", fake_auth_check)
    assert doctor.probe_hf_access("hf_x") == expected


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [(0, "running"), (1, "stopped"), (subprocess.TimeoutExpired("docker", 15), "stopped")],
)
def test_docker_probe_classifies_the_daemon(
    monkeypatch: pytest.MonkeyPatch, outcome: int | Exception, expected: DockerState
) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args[1:3] == ["info", "--format"]
        if isinstance(outcome, Exception):
            raise outcome
        return subprocess.CompletedProcess(args, outcome, stdout="", stderr="")

    def installed(name: str) -> str:
        return "/usr/bin/docker"

    monkeypatch.setattr(doctor.shutil, "which", installed)
    monkeypatch.setattr(doctor.subprocess, "run", fake_run)
    assert doctor.probe_docker() == expected


def test_default_probes_do_no_io_until_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MSHIFT_CACHE_DIR", str(tmp_path / "c"))
    probes = Probes.default()
    assert probes.cache_dir == tmp_path / "c"
    assert not probes.cache_dir.exists()
    assert probes.env["MSHIFT_CACHE_DIR"] == str(tmp_path / "c")
