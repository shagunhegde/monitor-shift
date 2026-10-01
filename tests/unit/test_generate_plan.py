import pytest
from inspect_ai.dataset import Sample

from monitor_shift.errors import ConfigError
from monitor_shift.generate.controlarena_runs import plan_samples

TASKS = [Sample(input=f"task {i}", id=f"t{i}") for i in range(5)]


def test_small_samples_use_distinct_tasks() -> None:
    plan = plan_samples(TASKS, 3, seed=1)
    assert len({s.id for s in plan}) == 3
    assert {s.id for s in plan} <= {s.id for s in TASKS}


def test_large_samples_use_every_task_evenly_with_unique_ids() -> None:
    plan = plan_samples(TASKS, 12, seed=1)
    assert len(plan) == 12
    assert len({s.id for s in plan}) == 12
    base = [str(s.id).split("__r")[0] for s in plan]
    assert all(base.count(f"t{i}") in (2, 3) for i in range(5))
    assert [s.id for s in TASKS] == [f"t{i}" for i in range(5)]  # originals untouched


def test_plans_are_seeded() -> None:
    assert [s.id for s in plan_samples(TASKS, 7, 3)] == [s.id for s in plan_samples(TASKS, 7, 3)]
    assert [s.id for s in plan_samples(TASKS, 7, 3)] != [s.id for s in plan_samples(TASKS, 7, 4)]


def test_empty_settings_are_an_error() -> None:
    with pytest.raises(ConfigError):
        plan_samples([], 3, seed=1)
