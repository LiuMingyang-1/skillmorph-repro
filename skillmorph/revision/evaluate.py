"""Proposal evaluation, selection, and application (paper 4.3).

One CoT call evaluates every proposal against its action's evidence, the
current skill contents (duplication/conflict, changes beyond evidence), and
the successful runs that rely on the edited contents. The LLM returns the
selected/rejected ids plus the complete new content of every file to change;
this module copies the input tree to output_dir and replaces only those
files, so no patch parser is needed and the input is never modified. Files
are applied only when the selection is non-empty.
"""

import difflib
import json

from ..llm import chat_json
from .prompts import load_prompt
from .skills import copy_skill_tree, read_skill_tree, write_artifact


def evaluate_and_patch(proposals, skill_dir, client=None, *, prompt_dir, output_dir):
    """Evaluate proposals, apply the consolidated revision to output_dir.

    Returns {selected, rejected, diff, skills_after}. Each proposal may carry
    "evidence"/"occurrences" or an embedded "edit_site"; either is forwarded
    so the LLM never evaluates an action_id with no evidence behind it.
    """
    files = read_skill_tree(skill_dir)
    copy_skill_tree(skill_dir, output_dir)

    if not proposals:
        return {
            "selected": [],
            "rejected": [],
            "diff": "",
            "skills_after": str(output_dir),
        }

    context = {
        "proposals": [
            {
                "action_id": p["action_id"],
                "rationale": p.get("rationale", ""),
                "edits": p.get("edits", []),
                "evidence": p.get("evidence")
                or p.get("edit_site", {}).get("evidence"),
                "occurrences": p.get("occurrences")
                or p.get("edit_site", {}).get("occurrences"),
            }
            for p in proposals
        ],
        "skill_contents": [
            {"path": rel, "content": content} for rel, content in files.items()
        ],
    }
    result = chat_json(
        [{"role": "user", "content": load_prompt(
            prompt_dir, "evaluate_select.txt"
        ).substitute(proposals_json=json.dumps(context))}],
        client=client,
    )

    selected = result["selected"]
    if not selected:
        return {
            "selected": [],
            "rejected": result["rejected"],
            "diff": "",
            "skills_after": str(output_dir),
        }

    after = dict(files)
    applied = []
    for entry in result["files"]:
        rel = f"{entry['skill']}/{entry['artifact']}"
        after[rel] = entry["content"]
        applied.append(rel)

    for rel in applied:
        write_artifact(
            output_dir, rel.split("/", 1)[0], rel.split("/", 1)[1], after[rel]
        )

    return {
        "selected": selected,
        "rejected": result["rejected"],
        "diff": _unified_diff(files, after),
        "skills_after": str(output_dir),
    }


NO_EOL = "\\ No newline at end of file"


def _diff_lines(text):
    """Split for difflib, embedding the no-EOL marker in the last line.

    A file without a trailing newline gets its final line suffixed with the
    standard marker, so whether that line is emitted as -, +, or context the
    hunk stays well-formed. File contents are never modified.
    """
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n" + NO_EOL + "\n"
    return lines


def _unified_diff(before, after):
    chunks = []
    for rel in sorted(set(before) | set(after)):
        old, new = before.get(rel, ""), after.get(rel, "")
        if old == new:
            continue
        chunks.append(
            "".join(
                difflib.unified_diff(
                    _diff_lines(old),
                    _diff_lines(new),
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                )
            )
        )
    return "\n".join(chunks)
