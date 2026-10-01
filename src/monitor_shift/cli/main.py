"""The `mshift` command line."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.markup import escape

from monitor_shift import __version__
from monitor_shift.errors import ConfigError, MonitorShiftError

app = typer.Typer(
    name="mshift",
    help="Measure how synthetic-calibrated agent monitor thresholds behave on real agent logs.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
console = Console()
err_console = Console(stderr=True)


def _fail(err: MonitorShiftError) -> NoReturn:
    err_console.print(f"[bold red]Error:[/] {escape(err.message)}", soft_wrap=True)
    err_console.print(f"[bold]Fix:[/] {escape(err.hint)}", soft_wrap=True)
    raise typer.Exit(2)


def _show_version(value: bool) -> None:
    if value:
        console.print(f"monitor-shift {__version__}", highlight=False)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_show_version, is_eager=True, help="Show the version."),
    ] = False,
) -> None:
    """Measure how synthetic-calibrated agent monitor thresholds behave on real agent logs."""
    if not os.environ.get("MSHIFT_NO_DOTENV"):
        from dotenv import find_dotenv, load_dotenv

        load_dotenv(find_dotenv(usecwd=True), override=False)  # API keys, MSHIFT_MODEL


def _model_default() -> str | None:
    return os.environ.get("MSHIFT_MODEL") or None


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


MaxUsd = Annotated[float, typer.Option("--max-usd", help="Stop before spending more than this.")]
Model = Annotated[
    str | None,
    typer.Option(help="Inspect model, e.g. openrouter/openai/gpt-6-luna (default: $MSHIFT_MODEL)."),
]


@app.command()
def doctor(
    offline: Annotated[
        bool, typer.Option("--offline", help="Skip checks that need the network.")
    ] = False,
    model: Annotated[
        str | None,
        typer.Option(help="Check the key for this Inspect model, e.g. openai/gpt-4.1-mini."),
    ] = None,
) -> None:
    """Check API keys, AI Village access, Docker and the cache; print one fix per problem."""
    from monitor_shift.cli.doctor import Probes, exit_code, render_checks, run_checks

    results = run_checks(Probes.default(), model=model or _model_default(), offline=offline)
    render_checks(results, console)
    raise typer.Exit(exit_code(results))


@app.command()
def demo(
    fake: Annotated[
        bool, typer.Option("--fake", help="Use synthetic fixtures and fake monitors.")
    ] = False,
    seed: Annotated[int, typer.Option(help="Seed for the fixtures.")] = 7,
    scale: Annotated[
        float, typer.Option(min=0.01, max=10.0, help="Multiply the Lite sample sizes.")
    ] = 1.0,
) -> None:
    """Run the whole pipeline end to end: fixtures, scoring, calibration, the ladder table."""
    if not fake:
        _fail(
            ConfigError(
                "The live demo needs a monitor model and arrives with milestone M1.",
                hint="uv run mshift demo --fake",
            )
        )
    from monitor_shift.cli.demo import render, run_demo

    start = time.perf_counter()
    result = run_demo(seed=seed, scale=scale)
    render(result, console)
    console.print(f"Finished in {time.perf_counter() - start:.1f}s.", highlight=False)


@app.command()
def fetch(
    source: Annotated[str, typer.Argument(help="swe-agent (aivillage once access is granted).")],
    n: Annotated[int, typer.Option("--n", min=1, help="How many trajectories.")] = 50,
    seed: Annotated[int, typer.Option(help="Sampling seed.")] = 7,
    name: Annotated[str | None, typer.Option(help="Name for the saved set.")] = None,
) -> None:
    """Pull a seeded sample of real trajectories into the local cache (never the repo)."""
    from monitor_shift.cli import live

    try:
        live.fetch(source, n, seed, name, console)
    except MonitorShiftError as err:
        _fail(err)


@app.command()
def generate(
    source: Annotated[str, typer.Argument(help="controlarena")],
    max_usd: MaxUsd,
    setting: Annotated[str, typer.Option(help="ControlArena setting.")] = "agentdojo",
    mode: Annotated[str, typer.Option(help="honest or attack.")] = "honest",
    n: Annotated[int, typer.Option("--n", min=1, help="How many runs.")] = 30,
    model: Model = None,
    seed: Annotated[int, typer.Option(help="Seed for task order.")] = 7,
    max_steps: Annotated[int, typer.Option(help="Agent step limit per run.")] = 25,
    name: Annotated[str | None, typer.Option(help="Name for the saved set.")] = None,
) -> None:
    """Run a ControlArena setting with an agent model to produce L0 trajectories."""
    from monitor_shift.cli import live

    try:
        if source != "controlarena":
            raise ConfigError(
                f"Can't generate from {source!r}.", hint="Use: mshift generate controlarena"
            )
        live.generate(
            setting,
            mode,
            n,
            live.require_model(model or _model_default()),
            seed,
            max_usd,
            name,
            max_steps,
            console,
        )
    except MonitorShiftError as err:
        _fail(err)


@app.command()
def score(
    source: Annotated[str, typer.Option(help="Saved trajectory set(s), comma-separated.")],
    max_usd: MaxUsd,
    monitors: Annotated[str, typer.Option(help="Comma-separated monitors.")] = "basic,hybrid",
    model: Model = None,
    samples: Annotated[int, typer.Option(min=1, max=10, help="Samples per monitor call.")] = 3,
    run: Annotated[str | None, typer.Option(help="Name for this scoring run.")] = None,
    max_tokens_in: Annotated[int, typer.Option(help="Truncation cap per trajectory.")] = 24_000,
    max_tokens_out: Annotated[int, typer.Option(help="Output allowance per sample.")] = 2_000,
    concurrency: Annotated[int, typer.Option(min=1, max=64, help="Parallel monitor calls.")] = 8,
) -> None:
    """Score saved trajectories with ControlArena monitors through Inspect, under --max-usd."""
    from monitor_shift.cli import live

    try:
        live.score(
            _csv(source),
            _csv(monitors),
            live.require_model(model or _model_default()),
            samples,
            max_usd,
            run,
            max_tokens_in,
            max_tokens_out,
            concurrency,
            console,
        )
    except MonitorShiftError as err:
        _fail(err)


@app.command()
def spike(
    run: Annotated[str, typer.Option(help="Scoring run(s) to report on, comma-separated.")],
    write: Annotated[Path | None, typer.Option(help="Also write the report here.")] = None,
) -> None:
    """The M1 go/no-go report: parse rates, truncation, cost, AUROC and projected spend."""
    from monitor_shift.cli import live

    try:
        live.spike(_csv(run), write, console)
    except MonitorShiftError as err:
        _fail(err)
