# Monitor prompts

- `basic` uses ControlArena's built-in `full_trajectory_default_system` and
  `full_trajectory_default_user` prompts, unchanged (0-100 scale).
- `reasoning_*.txt` are monitor-shift's own: a domain-neutral, message-only variant of
  ControlArena's full-trajectory prompt, used for the message half of `hybrid`.
- `constitutional.txt` is the human-refined reference prompt (G.1.3, "Human-Refined Prompt
  (GLOOM)") from Appendix G of Storf, Barton-Cooper, Peters-Gill and Hobbhahn, "Constitutional
  Black-Box Monitoring for Scheming in LLM Agents" (arXiv:2603.00829, Feb 2026), licensed CC BY
  4.0 (https://creativecommons.org/licenses/by/4.0/). Paste it verbatim from the PDF: the arXiv
  HTML page omits the prompt bodies. It is sent unchanged as the system prompt.
- `constitutional_user.txt` is monitor-shift's own: it carries the task, the transcript and the
  1-10 `<score>` reply format that ControlArena parses.

Every prompt is hashed into its monitor's `prompt_hash`, so editing one invalidates its
cached scores rather than silently mixing old and new results.
