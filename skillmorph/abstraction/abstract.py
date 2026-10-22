"""Abstract one raw trajectory into a state-transition sequence via an LLM.

The prompt asks the model to merge raw steps into meaningful operations and
emit (state_before, action, state_after) triples that map back to the raw
step indices they cover. We keep one transition per LLM-emitted item and
attach the union of the covered steps' skills_used / files_read so later
stages can trace evidence back to skill sources.
"""

from __future__ import annotations

from pathlib import Path

from .. import llm


def _load_prompt(prompt_dir: Path | str) -> str:
    return (Path(prompt_dir) / "abstract.txt").read_text(encoding="utf-8")


def _format_steps(steps: list[dict]) -> str:
    lines = []
    for i, step in enumerate(steps):
        parts = [f"step {i}: action={step['action']}"]
        if step.get("observation"):
            parts.append(f"observation={step['observation']}")
        if step.get("skills_used"):
            parts.append(f"skills_used={step['skills_used']}")
        if step.get("files_read"):
            parts.append(f"files_read={step['files_read']}")
        lines.append("\n  ".join(parts))
    return "\n".join(lines)


def abstract_run(raw: dict, *, prompt_dir, client=None) -> dict:
    """Abstract one raw run into a transition sequence.

    `raw` follows docs/INTERFACES.md stage-0 schema. Returns a dict with
    task_id / run_id / outcome / task preserved and `transitions`: a list of
    {k, state_before, action, state_after, skills_used, files_read,
    source_steps}. k is 1-based and indexes the returned transitions; the
    paper's (mu_{k-1}, a_k, mu_k) corresponds to transitions[k-1].
    source_steps are the 0-based raw step indices each transition covers,
    as reported by the model.
    """
    prompt = _load_prompt(prompt_dir)
    user = (
        f"Task: {raw['task']}\n\n"
        f"Trajectory steps:\n{_format_steps(raw['steps'])}\n\n"
        "Return the JSON object described in the system prompt."
    )
    result = llm.chat_json(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user},
        ],
        client=client,
    )

    steps = raw["steps"]
    transitions = []
    for k, tr in enumerate(result["transitions"], start=1):
        covered = tr["source_steps"]
        for idx in covered:
            if idx < 0 or idx >= len(steps):
                raise ValueError(
                    f"transition {k} references out-of-range source step {idx}"
                )
        skills_used = sorted({s for i in covered for s in steps[i].get("skills_used", [])})
        files_read = sorted({f for i in covered for f in steps[i].get("files_read", [])})
        transitions.append(
            {
                "k": k,
                "state_before": tr["state_before"],
                "action": tr["action"],
                "state_after": tr["state_after"],
                "skills_used": skills_used,
                "files_read": files_read,
                "source_steps": covered,
            }
        )

    return {
        "task_id": raw["task_id"],
        "run_id": raw["run_id"],
        "outcome": raw["outcome"],
        "task": raw["task"],
        "transitions": transitions,
    }
