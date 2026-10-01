"""AgentDojo through ControlArena and Inspect on the mock model: generation -> adapter."""

from pathlib import Path

import pytest
from control_arena import EvalMode

from monitor_shift.generate.controlarena_runs import generate_runs

pytestmark = [
    pytest.mark.slow,  # imports and runs the real AgentDojo environment
    # Inspect's eval leaves anyio streams for the garbage collector; not ours to fix.
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]


@pytest.mark.parametrize("mode", [EvalMode.HONEST, EvalMode.ATTACK])
def test_generates_labelled_l0_trajectories(mode: EvalMode, tmp_path: Path) -> None:
    run = generate_runs(
        "agentdojo",
        mode,
        3,
        "mockllm/model",
        seed=1,
        max_usd=1.0,
        log_dir=tmp_path / "logs",
        max_steps=2,
        require_price=False,
    )
    assert run.stopped is None
    assert len(run.trajectories) + run.no_trajectory == 3
    assert all(t.rung == "L0" and t.label == mode.value for t in run.trajectories)
    assert all(Path(p).exists() for p in run.log_paths)
