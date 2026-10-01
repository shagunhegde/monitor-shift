"""nebius/SWE-agent-trajectories (CC BY 4.0) -> Trajectories for rung L2.

Each row is one SWE-agent run on a GitHub issue. The first user turn holds the issue, after an
`ISSUE:` header. Each `ai` turn is discussion followed by one command in a fenced block, and the
next `user` turn is that command's output. Rows are fetched one at a time from the Hugging Face
rows API, so a sample never downloads the 5.3 GB dataset. A row whose cells the API truncated
is skipped and counted, since a cut transcript would misrepresent the run.
"""

from __future__ import annotations

import json
import random
import re
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from monitor_shift.errors import ConfigError
from monitor_shift.schema import Step, Trajectory, hash_text

DATASET = "nebius/SWE-agent-trajectories"
TOTAL_ROWS = 80_036
ROWS_API = "https://datasets-server.huggingface.co/rows"
DATASET_API = f"https://huggingface.co/api/datasets/{DATASET}"

_FENCE = re.compile(r"```[^\n]*\n(.*?)\n?```", re.S)
_ISSUE = re.compile(r"ISSUE:\s*\n(.*?)(?:\n\s*INSTRUCTIONS:|\Z)", re.S)


@dataclass(frozen=True)
class FetchedRow:
    row: Mapping[str, Any]
    truncated: bool


def split_turn(text: str) -> tuple[str, str]:
    """(discussion, command): the command is the last fenced block, if any."""
    blocks = list(_FENCE.finditer(text))
    if not blocks:
        return text.strip(), ""
    last = blocks[-1]
    return text[: last.start()].strip(), last.group(1).strip()


def _task(first_user: str, instance_id: str) -> str:
    match = _ISSUE.search(first_user)
    issue = match.group(1).strip() if match else first_user.strip()
    return f"Resolve this issue in the {_repo(instance_id)} repository:\n\n{issue}"


def _repo(instance_id: str) -> str:
    return instance_id.rsplit("-", 1)[0].replace("__", "/")


def parse_row(row: Mapping[str, Any], row_index: int, dataset_sha: str) -> Trajectory | None:
    turns: list[Mapping[str, Any]] = list(row.get("trajectory") or [])
    users = [t for t in turns if t.get("role") == "user"]
    if not users:
        return None
    steps: list[Step] = []
    observation: list[str] = []
    seen_task = False
    pending: tuple[str, str] | None = None

    def flush() -> None:
        nonlocal pending, observation
        if pending is not None:
            message, action = pending
            obs = "\n".join(observation) if observation else None
            if action or message:
                steps.append(Step(len(steps), action, obs, message or None))
        pending, observation = None, []

    for turn in turns:
        role, text = turn.get("role"), str(turn.get("text") or "")
        if role == "ai":
            flush()
            pending = split_turn(text)
        elif role == "user":
            if not seen_task:
                seen_task = True
            elif pending is not None:
                observation.append(text)
    flush()
    if not steps:
        return None
    instance_id = str(row.get("instance_id") or "unknown")
    model = str(row.get("model_name") or "unknown")
    return Trajectory(
        id=f"{instance_id}:{model}:{row_index}",
        source="swe_agent",
        rung="L2",
        task=_task(str(users[0].get("text") or ""), instance_id),
        steps=tuple(steps),
        label="unknown",
        meta={
            "instance_id": instance_id,
            "repo": _repo(instance_id),
            "agent_model": model,
            "resolved": str(row.get("target")),
            "exit_status": str(row.get("exit_status") or ""),
            "row": str(row_index),
            "dataset_sha": dataset_sha,
        },
    )


def _get_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read())


def fetch_row_from_hub(index: int) -> FetchedRow:
    query = urllib.parse.urlencode(
        {"dataset": DATASET, "config": "default", "split": "train", "offset": index, "length": 1}
    )
    payload = _get_json(f"{ROWS_API}?{query}")
    item = payload["rows"][0]
    return FetchedRow(row=item["row"], truncated=bool(item.get("truncated_cells")))


def dataset_sha_from_hub() -> str:
    return str(_get_json(DATASET_API)["sha"])


class SweAgentSource:
    """A seeded uniform sample of SWE-agent runs, skipping rows the API truncated."""

    def __init__(
        self,
        fetch_row: Callable[[int], FetchedRow] = fetch_row_from_hub,
        total_rows: int = TOTAL_ROWS,
        dataset_sha: str | None = None,
    ) -> None:
        self._fetch = fetch_row
        self.total_rows = total_rows
        self.dataset_sha = dataset_sha or dataset_sha_from_hub()
        self.skipped_truncated = 0
        self.skipped_empty = 0

    def fingerprint(self) -> str:
        return hash_text(json.dumps([DATASET, self.dataset_sha, self.total_rows]))

    def load(self, n: int, seed: int, stratify: Sequence[str] = ()) -> list[Trajectory]:
        if stratify:
            raise ConfigError(
                "The SWE-agent source doesn't stratify yet.",
                hint="Drop --stratify for swe-agent; uniform sampling is the M1 default.",
            )
        order = random.Random(f"{self.fingerprint()}:{seed}").sample(
            range(self.total_rows), self.total_rows
        )
        out: list[Trajectory] = []
        for index in order:
            if len(out) == n:
                break
            fetched = self._fetch(index)
            if fetched.truncated:
                self.skipped_truncated += 1
                continue
            traj = parse_row(fetched.row, index, self.dataset_sha)
            if traj is None:
                self.skipped_empty += 1
                continue
            out.append(traj)
        return out
