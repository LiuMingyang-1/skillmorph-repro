# exp_001 — first-loop pipeline smoke experiment

## Setup

- **Input data**: `data/trajectories.json` — hand-written **synthetic**
  trajectories (see `data/README.md`), not real agent runs. Two toy tasks
  around in-memory SQLite, two runs each, covering failed runs, clean
  successful runs, and one successful run containing a real
  error-introducing occurrence (`no such table` via a second connection,
  later repaired).
- **Skills**: `skills/sqlite-memory/` — a synthetic skill whose connection
  rules tell the agent to open a fresh `:memory:` connection per operation
  (the planted defect: every `:memory:` database is private to its
  connection).
- **Prompts**: `prompts/` — the five prompt templates for abstraction,
  error judging, localization, proposal, and evaluation.
- **Scope**: one round only (round_001): abstraction → unified actions →
  per-occurrence error judgment → coverage/ranking →
  localize/propose/evaluate → revised skill tree. No execution, no
  re-evaluation, no history.

## Expected outcome (hand-analysis of the synthetic data)

*If* the model marks opening the second connection in `task_002/run_2`
as error-introducing — the plausible reading (it produces the empty
database the later query hits), but a model judgment, not a guarantee —
"open a second in-memory connection" should rank first (failure
coverage in both failed runs plus that occurrence), localize
to `reference/connections.md`, and yield a revision that keeps setup
and queries on one connection. `skills_after/` and
`revision/skills.diff` hold the result; `analysis/` holds all
intermediate artifacts for manual audit.

## Status

Wiring verified offline (`.venv/bin/python -m pytest`, fake LLM client
with *scripted* replies — the scores/selections in tests are preset by
the fixture, not model output). Real-API results are **not verified** —
running the CLI makes paid OpenAI calls and has not been done; the
ranking/revision a real model produces is unknown until a real run is
checked by hand.
