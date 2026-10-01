# Decisions

Design decisions, and every place we built something instead of wrapping ControlArena or
Inspect. Newest milestone first. Deviations from `PREREG.md` go in `docs/deviations.md`, not here.

## M0 · Skeleton and quality gates (2026-09-30)

**D1. Our own tie-safe threshold instead of ControlArena's `compute_suspicion_threshold` (built).**
ControlArena returns `np.percentile(honest, 100 - budget)` and flags `score > threshold`. When
`n × budget` isn't a whole number, that flags more than the budget: 150 distinct scores at a 1%
budget flag 2 runs, i.e. 1.33%. The spec requires that the achieved rate never exceeds the target,
so `calibrate/thresholds.py` picks the lowest observed score whose flag rate is at most the
target, keeping ControlArena's strict `>`. Evidence:
`tests/unit/test_thresholds.py::test_achieved_rate_stays_under_target_where_a_percentile_would_not`
and the hypothesis properties in `tests/property/test_threshold_properties.py`. M3 adds bootstrap
intervals on top. This is the tie-aware helper named as an upstream PR candidate in M6.

**D2. The content hash covers what the monitor sees and nothing else.** `content_hash` is SHA-256
over JSON `[schema version, task, [[index, action, observation, message, timestamp], ...]]`. Ids,
labels, rung and meta are excluded, so relabeling or re-splitting never invalidates cached scores
(M2 keys the cache on this hash). JSON encoding stops text from moving between fields without
changing the hash. A stale hash raises `SchemaError` and is never silently recomputed. The scheme
is pinned by a snapshot test; changing it means bumping `SCHEMA_VERSION`.

**D3. Fixtures are generated in code, not stored as files.** `adapters/fixtures.py` builds
trajectories from templates that mimic the shape of each rung's source (AgentDojo tool calls,
BashArena shell work, SWE-agent edits, computer-use sessions). It writes no files, so no real
agent text can reach the repo. Item `i` depends only on (fingerprint, seed, i), so loads are
deterministic and prefix-stable. Benign-but-suspicious turns become more common along the ladder,
so the demo shows the effect under study. L2 and L3 fixtures are labeled `unknown`, since L2 is
only presumed benign and L3 is adjudicated.

**D4. The fake monitor is a test double, not a reimplementation of a ControlArena monitor
(built).** It matches regex categories (exfiltration, credentials, destructive, privilege, public
sharing, evasion), adds hash-seeded noise on the 1-10 scale, and averages `samples` draws the way
`ensemble_monitor_builder` does. Three variants mirror what `basic`, `hybrid` and
`constitutional` see. It exists so tests and `mshift demo --fake` run without keys, and it must
never produce study results.

**D5. `MonitorSpec.samples` defaults to 3**, per the Lite scope decision (the original spec said
5).

**D6. Wilson intervals come from statsmodels**, as the dependency table specifies. The result is
clipped to contain the point estimate, which guards against float noise at k = 0 and k = n.

**D7. `mshift doctor` treats Docker as a warning, not a failure.** Only L1 BashArena generation
needs Docker, and M1 may replace it with a Modal sandbox. A missing API key, missing AI Village
access or an unwritable cache are failures (exit code 1). Each check takes its I/O as an injected
probe, so every failure path is tested offline.

**D8. Tooling.** Python ≥ 3.11 (control-arena's floor), developed on 3.12, CI on 3.11 and 3.13.
Build backend: `uv_build`. `control-arena` is pinned to `==19.0.0`, since ControlArena API changes
are a listed risk. `inspect-ai` (0.3.273) is pinned through `uv.lock`, and CI installs with
`--locked`.

**D9. Pyright strict, with one scoped exception.** numpy 2.5.3's stubs leave an `Unknown` in the
overloads of `np.sort`, `np.unique`, `np.searchsorted`, `np.argmax` and `np.percentile`, and even
in `ndarray.searchsorted`. Under strict, every call to these is an error. The numpy-heavy
modules therefore turn off `reportUnknownMemberType` with a file-level comment. Every other
strict rule stays on everywhere. statsmodels ships no stubs, so its single call is cast at the
call site.

**D10. Ruff ignores Markdown.** ruff 0.16 formats Python code blocks inside `.md` files, and it
rewrote SPEC.md's hand-aligned interface block. The block was restored and `*.md` added to
`extend-exclude`.
