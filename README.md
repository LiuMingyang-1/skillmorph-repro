# SkillMorph reproduction

A minimal, dataset-agnostic reproduction of the first SkillMorph loop
(arXiv 2610.11858): given recorded agent trajectories and the skills the
agent consulted, localize suspicious actions, revise the responsible
skill contents, and keep every artifact for audit.

**First-version scope — one round only.** Trajectory abstraction →
unified actions → per-occurrence error judgment → coverage + suspicious
ranking → edit-site localization → proposals → evaluation + patch. No
execution stage (trajectories are an input, not produced here), no
re-evaluation of the revised skills, no multi-round history.

## Run

```bash
export OPENAI_API_KEY=...        # real run only; tests do not need it
uv run python -m skillmorph experiments/exp_001
```

The only argument is the experiment directory. Prints a JSON summary and
writes `experiments/exp_001/rounds/round_001/`. The run refuses to
overwrite an existing round directory — delete `rounds/round_001` first
to redo it.

## Experiment directory layout

```text
experiments/<exp>/
  prompts/            prompt templates used by every stage (see below)
  skills/             initial skill tree: <skill>/SKILL.md + artifacts
  data/trajectories.json   input trajectories (one JSON list of runs)
  rounds/round_001/
    prompts/          copy of the prompts actually used
    skills_before/    copy of the input skill tree
    trajectories/     the consumed input runs (one file each)
    analysis/         abstracted_runs.json, action_map.json,
                      coverage.json, ranking.json, summary.json
    revision/         edit_sites.json, proposals.json,
                      evaluation.json, skills.diff
    skills_after/     revised skill tree (clean copy if nothing applied)
```

## Input trajectory format

One run per object:

```json
{"task_id": "task_001", "run_id": "run_1",
 "task": "natural-language task", "outcome": "success | fail",
 "steps": [{"action": "...", "observation": "...",
            "skills_used": ["skill-name"],
            "files_read": ["skill-name/SKILL.md"]}]}
```

- `outcome` is the run's verdict, supplied by whatever produced the data.
- `skills_used`/`files_read` record consulted skills/artifacts; used as
  localization hints. Optional, default empty.
- A task's repeated runs are distinguished by `run_id`; coverage uses
  `task_id/run_id` as the run key.

`experiments/exp_001` ships a small **synthetic** example (clearly marked
as such) exercising the sqlite `:memory:`-connection trap: the skill says
open a new connection per operation, so cross-connection queries fail.

## Prompts

Five templates in the experiment's `prompts/` dir, consumed by:

| file | stage | returns |
|---|---|---|
| `abstract.txt` | trajectory → transitions | `{"transitions": [...]}` |
| `judge_error.txt` | per-occurrence error judgment | `{"introduces_error": bool, "reason": "..."}` |
| `localize.txt` | edit-site localization (`$mode` = artifacts/lines) | `{"locations": [...], "rationale": "..."}` |
| `propose.txt` | revision proposal | `{"edits": [...], "rationale": "..."}` |
| `evaluate_select.txt` | select + consolidate patch | `{"selected": [...], "rejected": [...], "files": [...]}` |

`localize.txt`/`propose.txt`/`evaluate_select.txt` are `string.Template`
files (`$placeholders`); `abstract.txt` is a system prompt;
`judge_error.txt` uses `{context}`/`{k}`/`{action}` placeholders.

## Configuration

All defaults live in `skillmorph/config.py`: `MODEL` (`gpt-4o`),
`TEMPERATURE`, `MAX_TOKENS`, `ERROR_WINDOW` (h), `TOP_N_SUSPICIOUS`,
`CLUSTER_DISTANCE`, plus `RUNS_PER_TASK` (documented for later loops).
The embedding model is `EMBEDDING_MODEL` in
`skillmorph/abstraction/cluster.py` (`text-embedding-3-small`). The API
key comes from `OPENAI_API_KEY`; no other provider is wired in.

## Offline tests vs. real runs

```bash
.venv/bin/python -m pytest -q   # or: uv run pytest — no network, no API key
```

The suite drives the whole pipeline with a scripted fake OpenAI client
(chat + embeddings) and checks every on-disk artifact, that the
evaluator actually receives the action's evidence, the applied skill
diff, and that inputs are preserved. All scores, selections, and
revisions in tests are **preset replies of the fixture** — the suite
verifies *wiring only*, not what a real model would decide.

Real paid API calls have **not** been run or validated — `python -m
skillmorph` on a real experiment is the unverified part; audit its
`analysis/` and `revision/` output by hand.
