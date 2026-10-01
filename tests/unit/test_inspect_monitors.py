from pathlib import Path

import pytest
from control_arena.monitor import MonitorResponse

from monitor_shift.errors import ConfigError
from monitor_shift.runner import inspect_monitors
from monitor_shift.runner.inspect_monitors import (
    MONITORS,
    check_monitors,
    component,
    monitor_spec,
    parse_response,
)
from monitor_shift.runner.truncate import TruncationRule


def ensemble_reason(samples: list[tuple[str, float]]) -> str:
    """The exact layout ControlArena's ensemble monitor writes."""
    return "\n\n".join(
        f"<sample_{i}>\n<reason>\n{reason}\n</reason>\n<score>{score}</score>\n</sample_{i}>"
        for i, (reason, score) in enumerate(samples)
    )


def test_single_sample_parse() -> None:
    ok = parse_response(MonitorResponse(suspicion_score=0.3, reason="looks fine"), 1)
    assert (ok.normalized, ok.parsed_samples) == (0.3, 1)
    bad = parse_response(
        MonitorResponse(suspicion_score=0.0, reason="No score found in model response"), 1
    )
    assert (bad.normalized, bad.parsed_samples) == (None, 0)


def test_ensemble_drops_failed_samples_instead_of_averaging_zero() -> None:
    reason = ensemble_reason(
        [("fine", 0.4), ("Could not parse score from model response", 0.0), ("odd", 0.8)]
    )
    parsed = parse_response(MonitorResponse(suspicion_score=0.4, reason=reason), 3)
    assert parsed.parsed_samples == 2
    assert parsed.normalized == pytest.approx(0.6)


def test_ensemble_with_no_parsed_samples_has_no_score() -> None:
    reason = ensemble_reason([("No score found in model response", 0.0)] * 3)
    parsed = parse_response(MonitorResponse(suspicion_score=0.0, reason=reason), 3)
    assert (parsed.normalized, parsed.parsed_samples) == (None, 0)


def test_unrecognised_ensemble_layout_falls_back_to_counting_failures() -> None:
    parsed = parse_response(MonitorResponse(suspicion_score=0.5, reason="new layout"), 3)
    assert (parsed.normalized, parsed.parsed_samples) == (0.5, 3)


def test_basic_uses_control_arenas_full_trajectory_prompts() -> None:
    from control_arena.monitor.prompts import monitor_prompts

    basic = component("basic")
    assert basic.system_prompt == monitor_prompts["full_trajectory_default_system"]
    assert basic.view == "actions"
    assert (basic.score_min, basic.score_max) == (0, 100)


def test_reasoning_prompt_has_the_formatter_placeholders() -> None:
    reasoning = component("reasoning")
    assert "{task_description}" in reasoning.user_prompt
    assert "{trajectory}" in reasoning.user_prompt
    assert reasoning.view == "messages"


def test_missing_constitutional_prompt_says_how_to_add_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(inspect_monitors, "PROMPTS_DIR", tmp_path)
    with pytest.raises(ConfigError) as info:
        component("constitutional")
    assert "G.1.3" in info.value.hint
    (tmp_path / "constitutional.txt").write_text("   \n")
    with pytest.raises(ConfigError):
        component("constitutional")


def test_pasted_constitutional_prompt_is_used_verbatim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    name = "constitutional_user.txt"
    (tmp_path / name).write_text((inspect_monitors.PROMPTS_DIR / name).read_text())
    pasted = "You are a monitor. Braces like {this} must survive untouched."
    (tmp_path / "constitutional.txt").write_text(pasted + "\n")
    monkeypatch.setattr(inspect_monitors, "PROMPTS_DIR", tmp_path)
    comp = component("constitutional")
    assert comp.system_prompt == pasted
    assert (comp.score_min, comp.score_max, comp.view) == (1, 10, "full")
    assert "{trajectory}" in comp.user_prompt
    assert "{task_description}" in comp.user_prompt


def test_spec_hash_tracks_prompts_rule_and_weights() -> None:
    rule = TruncationRule()
    basic = monitor_spec("basic", "m", 3, rule)
    assert basic == monitor_spec("basic", "m", 3, rule)
    assert basic.prompt_hash != monitor_spec("hybrid", "m", 3, rule).prompt_hash
    assert (
        basic.prompt_hash
        != monitor_spec("basic", "m", 3, TruncationRule(max_tokens=12_000)).prompt_hash
    )
    assert basic.max_tokens_in == rule.max_tokens


def test_hybrid_weights_are_the_preregistered_half_and_half() -> None:
    assert dict(MONITORS["hybrid"]) == {"basic": 0.5, "reasoning": 0.5}


def test_unknown_monitors_list_the_choices() -> None:
    with pytest.raises(ConfigError) as info:
        check_monitors(["basic", "paranoid"])
    assert "hybrid" in info.value.hint
