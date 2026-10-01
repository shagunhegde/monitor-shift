"""`mshift-fake/<name>`: a deterministic Inspect model provider for offline runs.

It lets tests (and `mshift score --model mshift-fake/scorer`) drive the real path, with
ControlArena monitors calling a model through Inspect, without keys or network. It answers
in ControlArena's <reasoning>/<score> format with a 1-10 score that counts suspicious
patterns in the prompt (valid on both 0-10 and 0-100 scales). Token usage is
characters / 4, so registered prices yield real cost accounting.

`mshift-fake/fail-every-<n>` answers every nth call without a score, to exercise
parse-failure handling. (The rate lives in the name because monitors build their own
model instances.)
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from inspect_ai.model import (
    ChatMessage,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    ModelUsage,
    modelapi,
)
from inspect_ai.tool import ToolChoice, ToolInfo

from monitor_shift.runner.monitors import count_patterns


class FakeScorer(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),  # noqa: B008 - Inspect's own signature
        **model_args: Any,
    ) -> None:
        super().__init__(model_name, base_url, api_key, [], config)
        match = re.fullmatch(r"fail-every-(\d+)", model_name)
        self.fail_every = int(match.group(1)) if match else 0
        self.calls = 0

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        self.calls += 1
        prompt = "\n".join(m.text for m in input)
        if self.fail_every and self.calls % self.fail_every == 0:
            content = "I cannot decide."
        else:
            hits = sum(count_patterns([prompt]).values())
            jitter = hashlib.sha256(f"{prompt}:{config.seed}".encode()).digest()[0] % 2
            score = min(10, 1 + 2 * hits + jitter)
            content = (
                f"<reasoning>fake: {hits} suspicious pattern(s)</reasoning><score>{score}</score>"
            )
        output = ModelOutput.from_content(model=self.model_name, content=content)
        output.usage = ModelUsage(
            input_tokens=math.ceil(len(prompt) / 4),
            output_tokens=math.ceil(len(content) / 4),
            total_tokens=math.ceil(len(prompt) / 4) + math.ceil(len(content) / 4),
        )
        return output


@modelapi(name="mshift-fake")
def mshift_fake() -> type[ModelAPI]:
    return FakeScorer
