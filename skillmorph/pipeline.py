"""First-loop experiment pipeline: trajectories -> revised skills.

Single round, no history. Layout under ``experiments/<exp>/``::

    data/trajectories.json   one JSON list of raw runs (docs/INTERFACES.md)
    prompts/                 prompt set used by every stage
    skills/                  initial skill tree
    rounds/round_001/
        prompts/        copy of the prompt set used
        skills_before/  copy of the input skill tree
        trajectories/   the input trajectories as consumed
        analysis/       abstracted runs, action map, coverage, ranking
        revision/       edit sites, proposals, evaluation and diff
        skills_after/   revised skill tree (verbatim copy if nothing applied)

``run_experiment`` refuses to overwrite an existing round directory. Every
artifact is plain JSON or text; exceptions propagate (no retries/fallbacks).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .abstraction import abstract_run, cluster_actions
from .attribution import coverage, mark_errors, rank
from .revision import evaluate_and_patch, localize, propose

DATA_FILE = "trajectories.json"
ROUND = "round_001"


def _load_runs(data_dir: Path) -> list[dict]:
    """Read ``data/trajectories.json``: one JSON list of raw runs.

    Every run needs task_id/run_id/outcome/steps (docs/INTERFACES.md).
    A missing file or field raises directly.
    """
    runs = json.loads((data_dir / DATA_FILE).read_text(encoding="utf-8"))
    for i, run in enumerate(runs):
        for key in ("task_id", "run_id", "outcome", "steps"):
            if key not in run:
                raise ValueError(f"run #{i} in {data_dir} is missing {key!r}")
    return runs


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _prepare_round(exp: Path) -> Path:
    """Create round_001 with its input snapshots; fail if it already exists."""
    round_dir = exp / "rounds" / ROUND
    round_dir.mkdir(parents=True, exist_ok=False)
    for sub in ("prompts", "skills_before", "trajectories", "analysis",
                "revision", "skills_after"):
        (round_dir / sub).mkdir()
    shutil.copytree(exp / "prompts", round_dir / "prompts", dirs_exist_ok=True)
    shutil.copytree(
        exp / "skills", round_dir / "skills_before", dirs_exist_ok=True
    )
    return round_dir


def _revision(ranked, skill_dir, runs, round_dir, *, prompt_dir, client):
    """localize -> propose -> evaluate_and_patch for each suspicious action."""
    rev_dir = round_dir / "revision"
    edit_sites, proposals = [], []
    for action in ranked:
        site = localize(
            action, skill_dir, runs, client=client, prompt_dir=prompt_dir
        )
        edit_sites.append(site)
        if site["locations"]:
            proposal = propose(site, client=client, prompt_dir=prompt_dir)
            # evaluate_and_patch needs the site's evidence/occurrences;
            # propose() itself only returns action_id/edits/rationale.
            proposals.append({**proposal, "edit_site": site})
    result = evaluate_and_patch(
        proposals,
        skill_dir,
        client=client,
        prompt_dir=prompt_dir,
        output_dir=round_dir / "skills_after",
    )
    _write_json(rev_dir / "edit_sites.json", edit_sites)
    _write_json(rev_dir / "proposals.json", proposals)
    _write_json(rev_dir / "evaluation.json", {
        "selected": result["selected"],
        "rejected": result["rejected"],
        "skills_after": result["skills_after"],
    })
    _write_text(rev_dir / "skills.diff", result["diff"])
    return result


def run_experiment(experiment_dir, *, client=None) -> dict:
    """Run one full loop of the pipeline over ``experiment_dir``.

    ``client`` is an OpenAI-compatible client (or fake) providing
    ``chat.completions.create`` and ``embeddings.create``; ``None`` uses the
    real OpenAI client (OPENAI_API_KEY). Returns the summary dict also
    written to ``rounds/round_001/analysis/summary.json``.
    """
    exp = Path(experiment_dir)
    prompt_dir = exp / "prompts"
    skill_dir = exp / "skills"
    raw_runs = _load_runs(exp / "data")
    if not raw_runs:
        raise ValueError(f"no trajectories found under {exp / 'data'}")

    round_dir = _prepare_round(exp)
    for run in raw_runs:
        _write_json(
            round_dir / "trajectories" / f"{run['task_id']}__{run['run_id']}.json",
            run,
        )

    analysis = round_dir / "analysis"
    runs = [
        abstract_run(run, prompt_dir=prompt_dir, client=client)
        for run in raw_runs
    ]
    action_map = cluster_actions(runs, client=client)
    runs = [
        mark_errors(run, prompt_dir=prompt_dir, client=client)
        if run["outcome"] == "success" else run
        for run in runs
    ]
    cov = coverage(runs)
    ranked = rank(cov, abstracted_runs=runs)

    _write_json(analysis / "abstracted_runs.json", runs)
    _write_json(analysis / "action_map.json", action_map)
    _write_json(analysis / "coverage.json", cov)
    _write_json(analysis / "ranking.json", ranked)

    result = _revision(
        ranked, skill_dir, runs, round_dir, prompt_dir=prompt_dir,
        client=client,
    )

    summary = {
        "experiment": exp.name,
        "round": ROUND,
        "runs": len(raw_runs),
        "actions_clustered": len(action_map),
        "suspicious_actions": [a["action_id"] for a in ranked],
        "selected": result["selected"],
        "rejected": result["rejected"],
        "diff_empty": not result["diff"],
        "skills_after": result["skills_after"],
    }
    _write_json(analysis / "summary.json", summary)
    return summary
