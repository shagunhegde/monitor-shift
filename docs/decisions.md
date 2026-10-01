# Decisions

Design decisions, and every place we built something instead of wrapping ControlArena or
Inspect. Newest milestone first. Deviations from `PREREG.md` go in `docs/deviations.md`, not here.

## M1 · Go/no-go spike (2026-10-01, in progress)

Entries marked *pending* wait on the paid spike runs and are completed with their evidence.

**D11. Scoring path: ControlArena's monitor agents, called directly in ControlArena's sample
context (path A, adapted).** `evaluate_monitors_post_hoc` scores every assistant message, which
is per-step scoring at N times the cost. Trajectory-level scoring needs one call over the whole
history. `run_monitor_for_messages(message_ids=...)` gets close, but it cuts the transcript at
the scored assistant message and drops the final tool output. So `runner/score.py` sets the
same `TaskState` context that `run_monitor_for_messages` sets, then calls the monitor built by
`basic_monitor_builder` or `ensemble_monitor_builder` (samples > 1) with
`full_trajectory_prompt_formatter_markdown`. Model calls, caching and cost accounting all stay
in Inspect. This is confirmed for `basic` and `hybrid` end to end, offline, through
ControlArena and Inspect against the `mshift-fake` provider
(`tests/integration/test_score.py`). *Pending:* `constitutional` (needs its prompt) and the
live models.

**D12. One rendering for every rung.** `runner/to_inspect.py` turns each step's action into a
tool call whose `view` is the action text, so ControlArena prints it verbatim. That means L0
logs are rendered exactly like SWE-agent and AI Village logs, and formatting can't confound the
ladder. The task isn't repeated inside the transcript, since the prompt already carries it.
`eval_mode` is always HONEST, so no monitor can learn a trajectory's label. The
ControlArena adapter drops the system prompt (it carries the side task in attack mode),
scaffold nudges and hidden reasoning blocks.

**D13. Monitor definitions.**
- `basic`: ControlArena's domain-neutral full-trajectory prompts (0-100), on actions and tool
  outputs.
- `hybrid`: 0.5 × `basic` + 0.5 × `reasoning`. `reasoning` is our message-only prompt,
  modelled on ControlArena's full-trajectory prompt; ControlArena's own `cot_only.txt` assumes
  a software-engineering task. If an agent wrote no messages, `hybrid` falls back to the
  action half, and the skip is recorded.
- `constitutional`: Apollo's Appendix G prompt (1-10, full view).

`basic` and `hybrid` share one cached call, so scoring both pays once.

**D14. Parse failures are counted, not scored as 0.** ControlArena scores an unparseable reply
0.0, and its ensemble averages that in. `parse_response` recognises ControlArena's fallback
reasons and per-sample blocks, drops failed samples, and voids a component if every sample
failed. M1's parse rate is reported per trajectory and per sample.

**D15. Spend caps wrap Inspect.** Inspect prices calls once a price is registered
(`set_model_info`) and enforces a `cost_limit`, but only after each call. For OpenRouter models
we register the live price from OpenRouter's public API. Each call first reserves a worst case
(input estimate × 1.3 plus the full output allowance), so runs stop *before* exceeding
`--max-usd`. Actual spend is read from Inspect's cost limits, which skip cache hits, so re-runs
cost $0. Generation runs in chunks, with a per-run Inspect `cost_limit` of the remaining budget
divided by the chunk size. ControlArena's placeholder model `none/none` is priced at $0,
because Inspect's `cost_limit` requires a price for every model in the eval.

**D16. Truncation rule.** Every field over 6,000 characters keeps its head and tail. Above
24,000 estimated tokens (characters / 4), the first quarter and the last steps are kept and the
gap gets one omission marker. Evidence on 50 L2 runs: 2,000-character field caps truncated
47/50 runs, almost all by clipping SWE-agent's ~5,000-character file views. With 6,000-character
caps, 17/50 are truncated at 24k (14 by dropping steps) and 24/50 at the 12k second cap.
*Pending:* chars/4 against billed tokens.

**D17. L0 attack runs use ControlArena's attack mode** (decided by the project lead,
2026-10-01). The agent is told to pursue an AgentDojo injection task covertly as its side task.
AgentDojo's prompt-injection attacks aren't used: they model a third-party threat, while the
monitors here target agent misbehaviour.

**D18. Provider: OpenRouter** (decided by the project lead, 2026-10-01). One key, many models,
and `:batch` variants at about half price. *Pending:* the default monitor model.

**D19. L2 sampling.** Rows are drawn uniformly with a seed and fetched one at a time from the
Hugging Face rows API, which avoids the 5.3 GB download. The API truncated 0 of 50 rows. Ids
add the row index, because instance + model isn't unique. Caveat for the writeup: the sampled
agents are Nebius's own Llama-based SWE-agents (8B and 70B), so L2 is real SWE-agent work but
not frontier-model work.

**D20. Docker for BashArena (L1): blocked on disk space.** BashArena needs a five-service
Docker Compose stack per task (agent box, router, logging, malware and database servers) with
`NET_ADMIN` and custom networks. Modal, first in the spec's order, is out: `inspect-sandboxes`
lists it as not supporting multi-service Compose. (Daytona does, through Docker-in-Docker, but
needs another account.) Next is local Docker. Docker Desktop starts fine on this Mac (arm64, 4
GB VM), but the host has 1.9 GB of free disk. BashArena builds an Ubuntu 22.04 image with
build tools for every task, plus three service images, which is likely several GB for one task
and far more for 300. The build was not attempted. Options: free about 20 GB and run L1
locally; use Daytona; or drop L1 as the spec allows (L0 to L2 then spans synthetic to real in
one step). *Pending:* that choice.

**D21. AgentDojo needs no Docker.** ControlArena's AgentDojo setting uses Inspect's local
sandbox. Verified by running honest and attack samples on the mock model
(`tests/integration/test_generate.py`).

**D22. Store.** M1 keeps trajectories and scores as JSON Lines under the cache directory, plus
`runs.jsonl` with each live command's config, versions, prices and spend. M2 moves scores to
the spec's parquet store.

**D23. Test plumbing.** Unix-domain sockets are allowed, because asyncio needs a socketpair;
network sockets stay blocked. Offline tests over ten seconds are marked `slow` and run in CI.
`mshift-fake/<name>` is an Inspect model provider, registered through Inspect's entry point,
that answers deterministically in ControlArena's format. It lets the full stack run without
keys.

**D24. The constitutional monitor uses G.1.3, pasted from the PDF.** Appendix G lists three
recommended prompts. We use G.1.3, the human-refined GLOOM prompt, which the paper reports as
best on held-out data. The arXiv HTML page omits the prompt bodies, so the prompt is pasted
verbatim from the PDF into `runner/prompts/constitutional.txt` (CC BY 4.0, attributed in
`runner/prompts/README.md`). It is sent unchanged as the system prompt. Our own
`constitutional_user.txt` carries the task, the transcript and the 1-10 `<score>` format.
*Pending:* the pasted prompt.

**D25. A ControlArena quirk, worked around.** `basic_monitor_builder` checks
`default_suspicion_score` against the raw score range, but ControlArena applies it on the 0-1
output range. So on a 1-10 scale only 1.0 is accepted, and the default 0.0 raises. We pass the
one value valid for both. It never affects results, because parse failures are detected from
the reason text (D14). This is a candidate for the upstream PR in M6.

**D26. Spike models.** The agent for L0 generation is `openrouter/qwen/qwen3.8-flash`. It
supports tool calls and comes from a different model family than the monitor, so the monitor
isn't judging its own family. The monitor candidates are `openrouter/openai/gpt-6-luna` ($0.10
/ $0.50 per million tokens) and, on L0 only, the cheaper `openrouter/deepseek/deepseek-v4-flash`.
`scripts/m1_spike.sh` runs the whole paid spike, with per-step caps adding up to $12.10.
*Pending:* the runs.

**Open: AI Village access** is reviewed manually by AI Digest and has been requested. The
adapter and the L3 measurements wait on it.

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
