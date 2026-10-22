"""Edit-site localization (paper 4.3).

Two-round narrowing instead of a tool-using agent: first the LLM picks the
relevant artifacts from an overview plus the recorded skill usage, then it
reads the numbered contents of those artifacts and cites line ranges. The
located contents are embedded into the returned edit_site so downstream
propose() needs no further skill-tree access. No fallbacks: whatever the LLM
selects is used as-is, and empty selections stay empty.
"""

import json

from ..llm import chat_json
from .prompts import load_prompt
from .skills import numbered, read_skill_tree, skill_overview


def _occurrences(action, runs):
    """Contexts of the suspicious action in its evidence runs."""
    wanted = set(action.get("fail_runs", [])) | set(action.get("succ_runs", []))
    out = []
    for run in runs:
        if f"{run['task_id']}/{run['run_id']}" not in wanted:
            continue
        transitions = run["transitions"]
        for k, tr in enumerate(transitions):
            if tr.get("action_id") != action["action_id"]:
                continue
            out.append(
                {
                    "run": f"{run['task_id']}/{run['run_id']}",
                    "outcome": run["outcome"],
                    "step": k,
                    "state_before": tr.get("state_before"),
                    "action": tr.get("action_text") or tr.get("action"),
                    "state_after": tr.get("state_after"),
                    "skills_used": tr.get("skills_used", []),
                    "files_read": tr.get("files_read", []),
                    # Per-occurrence judgments from mark_errors(); absent on
                    # failed runs, whose actions count as failure coverage
                    # without judgment — None there, never implies clean.
                    "introduces_error": tr.get("introduces_error"),
                    "error_reason": tr.get("error_reason"),
                    "prev_action": transitions[k - 1].get("action") if k else None,
                    "next_action": transitions[k + 1].get("action")
                    if k + 1 < len(transitions)
                    else None,
                }
            )
    return out


def _file_hints(action, runs, skills):
    """skill_dir-relative artifact paths the trajectory records as consulted.

    Passed to the LLM as localization evidence only; never merged into the
    selected files.
    """
    hints = set()
    wanted = set(action.get("fail_runs", [])) | set(action.get("succ_runs", []))
    for run in runs:
        if f"{run['task_id']}/{run['run_id']}" not in wanted:
            continue
        for tr in run["transitions"]:
            used = {s for s in tr.get("skills_used", []) if s in skills}
            hints.update(f"{s}/SKILL.md" for s in used)
            for rel in tr.get("files_read", []):
                hints.add(rel)
                hints.update(f"{s}/{rel}" for s in used)
    return hints


def localize(action, skill_dir, runs, client=None, *, prompt_dir):
    """Locate the skill contents guiding one suspicious action.

    Returns an edit_site dict: action_id, locations (skill/artifact/lines/
    content), rationale, evidence, and the occurrence contexts used.
    """
    files = read_skill_tree(skill_dir)
    contexts = _occurrences(action, runs)
    hints = _file_hints(action, runs, {rel.split("/", 1)[0] for rel in files})
    evidence = {
        "score": action.get("score"),
        "n_fail": action.get("n_fail"),
        "n_succ": action.get("n_succ"),
        "fail_runs": action.get("fail_runs", []),
        "succ_runs": action.get("succ_runs", []),
        "tasks": action.get("tasks", []),
    }
    payload = {
        "action_id": action["action_id"],
        "action_text": action.get("action_text"),
        "occurrences": contexts,
    }
    consulted = "\n".join(f"- {rel}" for rel in sorted(hints)) or "(none)"
    template = load_prompt(prompt_dir, "localize.txt")
    overview = skill_overview(files)

    first = chat_json(
        [{"role": "user", "content": template.substitute(
            mode="artifacts", action_json=json.dumps(payload),
            skill_overview=overview, candidates=consulted,
        )}],
        client=client,
    )
    if not first["locations"]:
        return {
            "action_id": action["action_id"],
            "locations": [],
            "rationale": first.get("rationale", ""),
            "evidence": evidence,
            "occurrences": contexts,
        }

    # Use exactly the files the LLM selected; unknown paths raise KeyError.
    selected, seen = [], set()
    for loc in first["locations"]:
        rel = f"{loc['skill']}/{loc['artifact']}"
        if rel not in seen:
            seen.add(rel)
            selected.append((rel, files[rel]))

    numbered_contents = "\n\n".join(
        f"### file: {rel}\n{numbered(content)}" for rel, content in selected
    )
    second = chat_json(
        [{"role": "user", "content": template.substitute(
            mode="lines", action_json=json.dumps(payload),
            skill_overview=overview, candidates=numbered_contents,
        )}],
        client=client,
    )

    locations = []
    for loc in second["locations"]:
        rel = f"{loc['skill']}/{loc['artifact']}"
        locations.append({**loc, "content": files[rel]})
    return {
        "action_id": action["action_id"],
        "locations": locations,
        "rationale": second.get("rationale", "") or first.get("rationale", ""),
        "evidence": evidence,
        "occurrences": contexts,
    }
