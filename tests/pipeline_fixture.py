"""Shared fixture for the offline pipeline tests: fake client + teaching data.

Story the fixture tells: two tasks exercise an "open a second in-memory
sqlite connection" action. It appears in two failed runs and in one
successful run where its (scripted) error-introduction judgment is true —
the suspicious action — while other actions split good/bad occurrences
across runs. All LLM replies here are scripted: they prove the wiring,
not what a real model would decide.
"""

import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

PROMPTS = Path(__file__).resolve().parent.parent / "experiments/exp_001/prompts"

SKILL_MD = "# sqlite-memory\n\nUse sqlite :memory: databases for tests.\n"
DB_MD = (
    "# Connections\n\n"
    "Line about imports.\n"
    "Line about queries.\n"
    "Open a new connection per operation.\n"   # the flawed rule (line 4)
)
NEW_DB_MD = (
    "# Connections\n\n"
    "Line about imports.\n"
    "Line about queries.\n"
    "Share ONE in-memory connection for imports and queries; each\n"
    "':memory:' database is private to its connection.\n"
)


def _embedded_json(text):
    """Pull the one JSON payload embedded in a substituted prompt."""
    for marker in ('{"proposals"', '{"action_id"'):
        i = text.find(marker)
        if i >= 0:
            return json.JSONDecoder().raw_decode(text[i:])[0]
    raise AssertionError("no embedded JSON payload in prompt")


class FakePipelineClient:
    """Routes each chat call by prompt markers; serves canned abstractions
    positionally and derives everything else from the request content."""

    def __init__(self, abstractions):
        self._abstract = list(abstractions)
        self.requests = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._chat)
        )
        self.embeddings = SimpleNamespace(create=self._embed)

    @staticmethod
    def _reply(payload):
        msg = SimpleNamespace(content=json.dumps(payload))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    def _chat(self, model, messages, **kwargs):
        text = "\n".join(m["content"] for m in messages)
        self.requests.append(text)
        if "abstract one agent execution" in text:
            return self._reply(self._abstract.pop(0))
        if "Judge the action at step" in text:
            action = re.search(
                r'Judge the action at step \d+: "(.*)"', text
            ).group(1)
            # Scripted judge: only opening the second :memory: connection is
            # marked error-introducing; querying it merely reveals the empty
            # database it produced.
            err = action in (
                "open second in-memory connection",
                "open a second in-memory connection",
            )
            return self._reply({"introduces_error": err, "reason": "fake"})
        if "Mode: artifacts" in text:
            payload = _embedded_json(text)
            # Only the second-connection actions are suspicious: the skill's
            # flawed "new connection per operation" rule is what they blame.
            locs = (
                [{"skill": "sqlite-memory",
                  "artifact": "reference/connections.md"}]
                if "second" in payload["action_text"]
                else []
            )
            return self._reply({"locations": locs, "rationale": "fake"})
        if "Mode: lines" in text:
            return self._reply({
                "locations": [{"skill": "sqlite-memory",
                               "artifact": "reference/connections.md",
                               "lines": [4, 4]}],
                "rationale": "per-operation connection rule splits the DB",
            })
        if "writing a revision proposal" in text:
            return self._reply({
                "edits": [{"skill": "sqlite-memory",
                           "artifact": "reference/connections.md",
                           "lines": [4, 4],
                           "change": "share one in-memory connection"}],
                "rationale": "fake",
            })
        if "evaluating revision proposals" in text:
            ctx = _embedded_json(text)
            return self._reply({
                "selected": [p["action_id"] for p in ctx["proposals"]],
                "rejected": [],
                "files": [{"skill": "sqlite-memory",
                           "artifact": "reference/connections.md",
                           "content": NEW_DB_MD}],
            })
        raise AssertionError(f"unexpected LLM call: {text[:120]}")

    def _embed(self, model, input):
        # Synonymous pair shares a fixed axis (cosine distance 0 -> one
        # cluster); every other text gets an orthogonal axis (distance 1).
        data = []
        for i, text in enumerate(input):
            vec = [0.0] * (len(input) + 1)
            vec[-1 if text in ("open second in-memory connection",
                               "open a second in-memory connection")
               else i] = 1.0
            data.append(SimpleNamespace(embedding=vec))
        return SimpleNamespace(data=data)


def _steps(*actions):
    steps = [
        {"action": "read sqlite-memory skill",
         "skills_used": ["sqlite-memory"],
         "files_read": ["sqlite-memory/SKILL.md"]}
    ]
    steps += [
        {"action": a, "observation": obs,
         "skills_used": [], "files_read": []}
        for a, obs in actions
    ]
    return steps


def _tr(source_steps, action, before, after):
    return {
        "state_before": before, "action": action,
        "state_after": after, "source_steps": source_steps,
    }


RUNS = [
    {"task_id": "t1", "run_id": "r1", "task": "doc store", "outcome": "fail",
     "steps": _steps(
         ("conn A: create documents, insert rows", "ok"),
         ("conn B = connect(':memory:')", "ok"),
         ("conn B: select from documents", "no such table: documents"))},
    {"task_id": "t1", "run_id": "r2", "task": "doc store", "outcome": "success",
     "steps": _steps(
         ("conn A: create documents, insert rows", "ok"),
         ("conn A: select from documents", "rows returned"))},
    {"task_id": "t2", "run_id": "r1", "task": "session store", "outcome": "fail",
     "steps": _steps(
         ("conn A: create users", "ok"),
         ("conn B = connect(':memory:'); insert via conn B", "ok"),
         ("conn A: select from users", "no such table: users"))},
    {"task_id": "t2", "run_id": "r2", "task": "session store",
     "outcome": "success",
     "steps": _steps(
         ("conn A: create users", "ok"),
         ("conn B = connect(':memory:') for scratch", "ok"),
         ("conn B: select from users", "no such table: users"),
         ("conn A: select from users", "rows returned"))},
]

# Abstraction replies in run order; each raw step covered exactly once.
ABSTRACTIONS = [
    {"transitions": [
        _tr([0, 1], "create table documents via connection A",
            "skill consulted", "documents created in conn A"),
        _tr([2], "open second in-memory connection",
            "documents in conn A", "conn B opened"),
        _tr([3], "query documents via the second connection",
            "conn B opened", "no such table: documents"),
    ]},
    {"transitions": [
        _tr([0, 1], "create table documents via connection A",
            "skill consulted", "documents created in conn A"),
        _tr([2], "query documents via the first connection",
            "documents in conn A", "rows returned"),
    ]},
    {"transitions": [
        _tr([0, 1], "create table users via connection A",
            "skill consulted", "users created in conn A"),
        _tr([2], "open a second in-memory connection",
            "users in conn A", "conn B opened"),
        _tr([3], "query users via the first connection",
            "conn B opened", "no such table: users"),
    ]},
    {"transitions": [
        _tr([0, 1], "create table users via connection A",
            "skill consulted", "users created in conn A"),
        _tr([2], "open a second in-memory connection",
            "users in conn A", "conn B opened"),
        _tr([3], "query users via the second connection",
            "conn B opened", "no such table: users"),
        _tr([4], "query users via the first connection",
            "conn B empty", "rows returned"),
    ]},
]

# Clean all-success input for the no-change test.
RUNS_ALL_SUCCESS = [
    {"task_id": "t1", "run_id": "r1", "task": "doc store",
     "outcome": "success",
     "steps": _steps(("conn A: create documents", "ok"),
                     ("conn A: select", "rows"))},
    {"task_id": "t1", "run_id": "r2", "task": "doc store",
     "outcome": "success",
     "steps": _steps(("conn A: create documents", "ok"),
                     ("conn A: select", "rows"))},
]
ABSTRACTIONS_ALL_SUCCESS = [
    {"transitions": [
        _tr([0, 1], "create table documents via connection A", "s", "t"),
        _tr([2], "query documents via the first connection", "t", "u"),
    ]},
    {"transitions": [
        _tr([0, 1], "create table documents via connection A", "s", "t"),
        _tr([2], "query documents via the first connection", "t", "u"),
    ]},
]


def make_experiment(tmp_path, runs):
    """Create a minimal experiment dir: data + copied prompts + one skill."""
    exp = tmp_path / "exp"
    (exp / "data").mkdir(parents=True)
    (exp / "data" / "trajectories.json").write_text(json.dumps(runs))
    shutil.copytree(PROMPTS, exp / "prompts")
    ref = exp / "skills" / "sqlite-memory" / "reference"
    ref.mkdir(parents=True)
    (exp / "skills" / "sqlite-memory" / "SKILL.md").write_text(SKILL_MD)
    (ref / "connections.md").write_text(DB_MD)
    return exp


def tree_snapshot(root):
    """{relative_path: content} for every file under root."""
    root = Path(root)
    return {
        str(p.relative_to(root)): p.read_text()
        for p in root.rglob("*") if p.is_file()
    }
