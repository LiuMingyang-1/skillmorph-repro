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
- **Scope**: independent runs (`runs/run_NNN/`): abstraction → unified
  actions → per-occurrence error judgment → coverage/ranking →
  localize/propose/evaluate → revised skill tree. Each run reads the
  experiment root inputs; no execution, no re-evaluation, no history.
- **Archive**: `archive/round_001/` — artifacts of an early paid attempt
  kept as-is for reference (not read by new runs).

## Expected outcome (hand-analysis of the synthetic data)

*If* the model marks opening the second connection in `task_002/run_2`
as error-introducing — the plausible reading (it produces the empty
database the later query hits), but a model judgment, not a guarantee —
"open a second in-memory connection" should rank first (failure
coverage in both failed runs plus that occurrence), localize
to `reference/connections.md`, and yield a revision that keeps setup
and queries on one connection. The run's `skills_after/` and
`revision/skills.diff` hold the result; `analysis/` holds all
intermediate artifacts for manual audit.

## Status

On 2026-10-27, commit `a912de9` completed one real-API run in about 73
seconds (exit 0), after 52 offline tests passed. Results are preserved in
`runs/run_001/`; see `REPORT.md`, `analysis/`, and `revision/skills.diff`.
Both chat and embedding calls succeeded. The revision replaces the planted
fresh-connection rule with a shared connection for setup and queries.

The result has important limitations: 14 transitions map to only two action
clusters, mixing setup, opening a second connection, and queries. Both clusters
have the same suspiciousness score. Error-introduction judgments differ from
the earlier archived attempt. The cause of the broad clustering is not yet
isolated; input representation, embeddings, and the clustering threshold need
inspection. No task was re-executed with the revised skill, so efficacy remains
unverified. Usage and cost were not recorded.

Next: inspect action representation and clustering boundaries offline before
changing parameters or starting another paid run. Preserve this run as the
baseline evidence.
