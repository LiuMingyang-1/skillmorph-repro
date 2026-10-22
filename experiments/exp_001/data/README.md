# Synthetic teaching data (not real trajectories)

`trajectories.json` is a **hand-written synthetic** input file — no agent
ever produced these runs. It exists so the pipeline can be exercised
end-to-end and its artifacts inspected. Nothing about it constitutes a real
experiment or evidence of effect.

Format (one JSON list; one element per run — see `docs/INTERFACES.md`):

```json
{
  "task_id": "task_001",
  "run_id": "run_1",
  "task": "natural-language task description",
  "outcome": "success | fail",
  "steps": [
    {"action": "what the agent did",
     "observation": "what came back",
     "skills_used": ["skill-name"],
     "files_read": ["skill-name/SKILL.md"]}
  ]
}
```

Story: two toy tasks ("doc store", "session store") each ask for an
in-memory SQLite database. The `sqlite-memory` skill tells the agent to
open a fresh `:memory:` connection per operation — but every `:memory:`
database is private to its connection, so a second connection sees an
empty database. The trajectories contain:

- failed runs where the agent opens a second connection and queries an
  empty database,
- a successful run that only ever uses one connection,
- a successful run where the agent queries through a second connection,
  hits `no such table`, recovers by re-querying through the first
  connection, and passes — an error-introducing occurrence inside a
  successful run for `mark_errors` to find.
