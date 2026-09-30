"""One contract every Source must pass. Later adapters join SOURCES, run on fixture files."""

import pytest

from monitor_shift.adapters.fixtures import FixtureSource
from monitor_shift.schema import Source

SOURCES: list[Source] = [
    FixtureSource("L0", "honest", split="calibration"),
    FixtureSource("L0", "honest", split="heldout"),
    FixtureSource("L0", "attack"),
    FixtureSource("L1", "honest"),
    FixtureSource("L2", "unknown"),
    FixtureSource("L3", "unknown"),
]
IDS = [s.fingerprint()[:12] for s in SOURCES]


@pytest.fixture(params=SOURCES, ids=IDS)
def source(request: pytest.FixtureRequest) -> Source:
    return request.param


def test_returns_the_requested_count(source: Source) -> None:
    assert len(source.load(n=40, seed=1)) == 40


def test_ids_are_unique(source: Source) -> None:
    ids = [t.id for t in source.load(n=300, seed=1)]
    assert len(set(ids)) == len(ids)


def test_hashes_are_stable_across_loads(source: Source) -> None:
    first = [(t.id, t.content_hash) for t in source.load(n=50, seed=3)]
    again = [(t.id, t.content_hash) for t in source.load(n=50, seed=3)]
    assert first == again


def test_a_new_seed_gives_new_content(source: Source) -> None:
    a = {t.content_hash for t in source.load(n=50, seed=3)}
    b = {t.content_hash for t in source.load(n=50, seed=4)}
    assert a.isdisjoint(b)


def test_no_empty_tasks_or_actions(source: Source) -> None:
    for traj in source.load(n=100, seed=1):
        assert traj.task.strip()
        assert traj.steps
        assert all(step.action.strip() or (step.message or "").strip() for step in traj.steps)


def test_fingerprint_is_stable(source: Source) -> None:
    assert source.fingerprint() == source.fingerprint()


def test_fingerprints_are_distinct_across_sources() -> None:
    prints = [s.fingerprint() for s in SOURCES]
    assert len(set(prints)) == len(prints)
