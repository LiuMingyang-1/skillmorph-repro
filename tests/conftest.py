"""修订阶段测试共用的离线夹具。"""

from pathlib import Path
from types import SimpleNamespace

import pytest


class FakeClient:
    """按队列提供 assistant 回复，并记录每次请求。"""

    def __init__(self, *contents):
        self._contents = list(contents)
        self.requests = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, model, messages, **kwargs):
        self.requests.append({"model": model, "messages": messages, **kwargs})
        assert self._contents, "fake client has no queued reply"
        content = self._contents.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


PROMPTS = Path(__file__).resolve().parent.parent / "experiments/exp_001/prompts"

SKILL_A = """# builder

## Building and Running

npm run build must succeed.

## Quality Checklist

Run the test suite.
"""

SKILL_B = """# writer

Write files with care.
"""

RUNS = [
    {
        "task_id": "t1",
        "run_id": "r1",
        "outcome": "fail",
        "transitions": [
            {
                "action_id": "act_001",
                "action_text": "open second in-memory connection",
                "action": "open second in-memory connection",
                "state_before": "imported docs via connection A",
                "state_after": "no such table: documents",
                "skills_used": ["builder"],
                "files_read": ["builder/SKILL.md"],
            }
        ],
    },
    {
        "task_id": "t1",
        "run_id": "r2",
        "outcome": "fail",
        "transitions": [
            {
                "action_id": "act_001",
                "action_text": "query through connection B",
                "state_before": "db ready",
                "state_after": "query failed",
                "skills_used": ["builder"],
                "files_read": [],
            }
        ],
    },
]

ACTION = {
    "action_id": "act_001",
    "action_text": "open a separate in-memory DB connection",
    "score": 0.61,
    "n_fail": 2,
    "n_succ": 0,
    "fail_runs": ["t1/r1", "t1/r2"],
    "succ_runs": [],
    "tasks": ["t1"],
}


@pytest.fixture()
def skill_dir(tmp_path):
    root = tmp_path / "skills"
    (root / "builder").mkdir(parents=True)
    (root / "builder" / "reference").mkdir()
    (root / "writer").mkdir()
    (root / "builder" / "SKILL.md").write_text(SKILL_A)
    (root / "builder" / "reference" / "db.md").write_text(
        "# db\n\nOpen one connection per operation.\n"
    )
    (root / "writer" / "SKILL.md").write_text(SKILL_B)
    return root
