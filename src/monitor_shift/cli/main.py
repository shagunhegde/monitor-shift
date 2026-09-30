"""The `mshift` command line."""

from __future__ import annotations

import time
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

    results = run_checks(Probes.default(), model=model, offline=offline)
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
