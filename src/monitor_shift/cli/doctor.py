"""`mshift doctor`: check keys, AI Village access, Docker and the cache; print one fix each.

Each check takes its I/O as an injected probe, so tests can exercise every failure offline.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from monitor_shift.runner.cache import cache_dir

Status = Literal["ok", "warn", "fail"]
HubAccess = Literal["ok", "gated", "unauthorized", "not_found", "network"]
DockerState = Literal["running", "stopped", "missing"]

AIVILLAGE_REPO = "aidigestorg/ai-village"
AIVILLAGE_URL = f"https://huggingface.co/datasets/{AIVILLAGE_REPO}"
RERUN = "then rerun `uv run mshift doctor`"

# Inspect provider prefix -> env vars that hold its key.
PROVIDER_KEYS: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "google": ("GOOGLE_API_KEY",),
    "mistral": ("MISTRAL_API_KEY",),
    "grok": ("XAI_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "together": ("TOGETHER_API_KEY",),
    "fireworks": ("FIREWORKS_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
}
LOCAL_PROVIDERS = frozenset({"hf", "vllm", "ollama", "llama-cpp-python", "sglang", "mockllm"})
MODEL_ENV_VARS = ("MSHIFT_MODEL", "INSPECT_EVAL_MODEL")


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    detail: str
    fix: str | None


@dataclass(frozen=True)
class Probes:
    env: Mapping[str, str]
    hf_token: Callable[[], str | None]
    hf_access: Callable[[str | None], HubAccess]
    docker: Callable[[], DockerState]
    cache_dir: Path
    platform: str

    @classmethod
    def default(cls) -> Probes:
        from huggingface_hub import get_token

        return cls(
            env=dict(os.environ),
            hf_token=get_token,
            hf_access=probe_hf_access,
            docker=probe_docker,
            cache_dir=cache_dir(),
            platform=sys.platform,
        )


# --- Probes (real I/O) ----------------------------------------------------------------------


def probe_hf_access(token: str | None) -> HubAccess:
    from huggingface_hub import auth_check
    from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, RepositoryNotFoundError

    try:
        auth_check(AIVILLAGE_REPO, repo_type="dataset", token=token)
    except GatedRepoError:
        return "gated"
    except RepositoryNotFoundError:
        return "not_found"
    except HfHubHTTPError as err:
        status = err.response.status_code if err.response is not None else None
        return "unauthorized" if status in (401, 403) else "network"
    except OSError:  # includes requests' ConnectionError and offline mode
        return "network"
    return "ok"


def probe_docker() -> DockerState:
    exe = shutil.which("docker")
    if exe is None:
        return "missing"
    try:
        done = subprocess.run(
            [exe, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "stopped"
    return "running" if done.returncode == 0 else "stopped"


# --- Checks (pure given their probes) -------------------------------------------------------


def check_api_keys(env: Mapping[str, str], model: str | None) -> CheckResult:
    name = "API key"

    def has(key: str) -> bool:
        return bool(env.get(key, "").strip())

    model = model or next((env[v] for v in MODEL_ENV_VARS if has(v)), None)
    if model:
        provider = model.split("/", 1)[0]
        if provider in LOCAL_PROVIDERS:
            return CheckResult(name, "ok", f"{model} runs locally; no key needed", None)
        keys = PROVIDER_KEYS.get(provider)
        if keys is None:
            return CheckResult(
                name,
                "warn",
                f"Can't check credentials for provider {provider!r} ({model})",
                f"Set {provider}'s credentials as Inspect expects: "
                "https://inspect.aisi.org.uk/providers.html",
            )
        if any(has(k) for k in keys):
            return CheckResult(name, "ok", f"{keys[0]} is set for {model}", None)
        return CheckResult(
            name,
            "fail",
            f"{model} needs {keys[0]}, which isn't set, so live scoring would fail",
            f"export {keys[0]}=...  {RERUN}",
        )
    present = [p for p, keys in PROVIDER_KEYS.items() if any(has(k) for k in keys)]
    if present:
        return CheckResult(name, "ok", f"keys found for: {', '.join(present)}", None)
    return CheckResult(
        name,
        "fail",
        "No model API key found, so live scoring would fail (demo --fake needs none)",
        "export OPENAI_API_KEY=...  (or another Inspect provider's key; "
        f"add --model provider/name to check one), {RERUN}",
    )


def check_aivillage(
    token: str | None, access: Callable[[str | None], HubAccess], offline: bool
) -> CheckResult:
    name = "AI Village access"
    if not token:
        return CheckResult(
            name,
            "fail",
            "No Hugging Face token, so the gated AI Village dataset can't be downloaded",
            f"Accept the terms at {AIVILLAGE_URL}, run `hf auth login`, {RERUN}",
        )
    if offline:
        return CheckResult(
            name,
            "warn",
            "Token found; dataset access not checked (--offline)",
            f"Run `uv run mshift doctor` without --offline to check access to {AIVILLAGE_REPO}",
        )
    outcomes: dict[HubAccess, CheckResult] = {
        "ok": CheckResult(name, "ok", f"token can read {AIVILLAGE_REPO}", None),
        "gated": CheckResult(
            name,
            "fail",
            f"Your token can't read {AIVILLAGE_REPO} yet: its terms haven't been accepted",
            f"Accept the terms at {AIVILLAGE_URL} with the same account, {RERUN}",
        ),
        "unauthorized": CheckResult(
            name,
            "fail",
            "Hugging Face rejected your token",
            f"Run `hf auth login` with a valid read token, {RERUN}",
        ),
        "not_found": CheckResult(
            name,
            "fail",
            f"{AIVILLAGE_REPO} wasn't found with your token (private, moved, or no read access)",
            f"Open {AIVILLAGE_URL} while logged in, run `hf auth login` again, {RERUN}",
        ),
        "network": CheckResult(
            name,
            "warn",
            "Couldn't reach huggingface.co to check access",
            f"Check your connection and that HF_HUB_OFFLINE is unset, {RERUN}",
        ),
    }
    return outcomes[access(token)]


def check_docker(probe: Callable[[], DockerState], platform: str) -> CheckResult:
    name = "Docker"
    why = "It's needed only to generate L1 BashArena runs"
    state = probe()
    if state == "running":
        return CheckResult(name, "ok", "Docker daemon is running", None)
    if state == "missing":
        return CheckResult(
            name,
            "warn",
            f"Docker CLI not found. {why}",
            f"Install Docker from https://docs.docker.com/get-docker/, {RERUN}",
        )
    if platform == "darwin":
        start = "Start Docker Desktop with `open -a Docker`"
    elif platform == "win32":
        start = "Start Docker Desktop from the Start menu"
    else:
        start = "Start the daemon with `sudo systemctl start docker`"
    return CheckResult(name, "warn", f"Docker daemon isn't running. {why}", f"{start}, {RERUN}")


def check_cache(path: Path) -> CheckResult:
    name = "Cache"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".mshift-write-test-{os.getpid()}"
        probe.write_text("ok")
        probe.unlink()
    except OSError as err:
        return CheckResult(
            name,
            "fail",
            f"Cache dir {path} isn't a writable directory ({err.strerror or err})",
            f"export MSHIFT_CACHE_DIR=<a writable directory>, {RERUN}",
        )
    files = [p for p in path.rglob("*") if p.is_file()]
    size_mb = sum(p.stat().st_size for p in files) / 1e6
    return CheckResult(name, "ok", f"{path} ({len(files)} files, {size_mb:.1f} MB)", None)


def run_checks(probes: Probes, model: str | None, offline: bool) -> list[CheckResult]:
    return [
        check_api_keys(probes.env, model),
        check_aivillage(probes.hf_token(), probes.hf_access, offline),
        check_docker(probes.docker, probes.platform),
        check_cache(probes.cache_dir),
    ]


def exit_code(results: Sequence[CheckResult]) -> int:
    return 1 if any(r.status == "fail" for r in results) else 0


_STYLE: dict[Status, str] = {"ok": "green", "warn": "yellow", "fail": "bold red"}


def render_checks(results: Sequence[CheckResult], console: Console) -> None:
    table = Table(title="mshift doctor", title_justify="left")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    for r in results:
        table.add_row(r.name, f"[{_STYLE[r.status]}]{r.status}[/]", escape(r.detail))
    console.print(table)
    problems = [r for r in results if r.fix]
    for r in problems:
        fix = escape(r.fix or "")
        console.print(f"[{_STYLE[r.status]}]{r.name}[/]: {fix}", soft_wrap=True, highlight=False)
    if not problems:
        console.print("All checks passed.")
    else:
        fails = sum(r.status == "fail" for r in results)
        warns = sum(r.status == "warn" for r in results)
        console.print(f"{fails} failed, {warns} warning(s).")
