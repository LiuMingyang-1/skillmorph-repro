"""LLM judgment of whether an action occurrence introduced an error.

Per paper §4.2: only successful runs are inspected. For each transition k,
the window of `ERROR_WINDOW` steps before and after k is shown to the LLM,
which decides whether the action introduced an error state (an unresolved
error or failed validation) rather than merely revealing an existing one.
Failed runs take no judgment: every action in them receives failure coverage
directly.
"""

from pathlib import Path

from .. import config
from ..llm import chat_json


def _load_prompt(prompt_dir: Path) -> str:
    return (prompt_dir / "judge_error.txt").read_text()


def _window(transitions: list[dict], k: int) -> tuple[list[dict], int]:
    """Transitions within ERROR_WINDOW steps of step index k (0-based),
    plus the original index of the first returned transition."""
    lo = max(0, k - config.ERROR_WINDOW)
    hi = min(len(transitions), k + config.ERROR_WINDOW + 1)
    return transitions[lo:hi], lo


def _format_context(transitions: list[dict], offset: int = 0) -> str:
    lines = []
    for i, t in enumerate(transitions):
        action = t.get("action_text") or t.get("action", "")
        lines.append(
            f"step {offset + i}: action={action!r}\n"
            f"  state_before: {t.get('state_before', '')}\n"
            f"  state_after: {t.get('state_after', '')}"
        )
    return "\n".join(lines)


def mark_errors(run: dict, *, prompt_dir, client=None) -> dict:
    """Mark each transition of a successful run with `introduces_error`.

    Mutates a copy: returns a new run dict with `introduces_error` (bool) and
    `error_reason` (str) set on every transition. Raises ValueError when run
    outcome is not "success"; failed runs need no judgment (all actions count
    as failure coverage).
    """
    if run.get("outcome") != "success":
        raise ValueError(
            f"mark_errors only applies to successful runs, got {run.get('outcome')!r}"
        )
    template = _load_prompt(Path(prompt_dir))
    transitions = run["transitions"]
    out = dict(run)
    out_transitions = []
    for k, transition in enumerate(transitions):
        window, offset = _window(transitions, k)
        prompt = template.format(
            context=_format_context(window, offset),
            k=k,
            action=transition.get("action_text") or transition.get("action", ""),
        )
        result = chat_json(
            [{"role": "user", "content": prompt}],
            client=client,
        )
        t = dict(transition)
        t["introduces_error"] = result["introduces_error"]
        t["error_reason"] = str(result.get("reason", ""))
        out_transitions.append(t)
    out["transitions"] = out_transitions
    return out
