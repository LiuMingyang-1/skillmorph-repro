"""Offline tests for skillmorph.abstraction with fake LLM/embedding clients."""

import json
import math
from types import SimpleNamespace

import pytest

from skillmorph.abstraction import abstract_run, cluster_actions


def _chat_client(payload):
    """Fake OpenAI client whose chat.completions.create returns `payload`."""
    message = SimpleNamespace(content=json.dumps(payload))
    completions = SimpleNamespace(
        create=lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=message)])
    )
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def _vec(text, dims):
    """Deterministic pseudo-embedding: unit vector scaled by char codes."""
    v = [0.0] * dims
    for i, ch in enumerate(text):
        v[i % dims] += (ord(ch) % 17) / 17.0
    return v


def _embedding_client(similar_pairs):
    """Fake client where texts in `similar_pairs` share vectors; others differ.

    similar_pairs: list of (text_a, text_b); both map to the same vector so
    their cosine distance is 0. Texts not in any pair get a unique axis.
    """
    groups = {}
    dims = 8
    for a, b in similar_pairs:
        groups.setdefault(a, _vec(a, dims))
        groups[b] = groups[a]

    def create(model, input):
        data = []
        for text in input:
            vec = groups.get(text)
            if vec is None:
                vec = [0.0] * dims
                vec[hash(text) % dims] = 1.0
            data.append(SimpleNamespace(embedding=vec))
        return SimpleNamespace(data=data)

    return SimpleNamespace(embeddings=SimpleNamespace(create=create))


RAW = {
    "task_id": "task_001",
    "run_id": "run_1",
    "task": "Fix the MCP server",
    "outcome": "fail",
    "steps": [
        {
            "action": "read_file(path='SKILL.md')",
            "observation": "skill text",
            "skills_used": ["mcp-builder"],
            "files_read": ["SKILL.md"],
        },
        {
            "action": "run_tests()",
            "observation": "2 failed",
            "skills_used": [],
            "files_read": [],
        },
        {
            "action": "edit_file(path='db.py')",
            "observation": "edited",
            "skills_used": ["mcp-builder"],
            "files_read": ["reference/node_mcp_server.md"],
        },
    ],
}


class TestAbstractRun:
    def test_transitions_preserve_source_and_metadata(self, tmp_path):
        (tmp_path / "abstract.txt").write_text("prompt body")
        payload = {
            "transitions": [
                {
                    "state_before": "repo present",
                    "action": "read the skill doc",
                    "state_after": "skill rules known",
                    "source_steps": [0],
                },
                {
                    "state_before": "tests failing",
                    "action": "edit db.py",
                    "state_after": "edit applied",
                    "source_steps": [1, 2],
                },
            ]
        }
        out = abstract_run(RAW, prompt_dir=tmp_path, client=_chat_client(payload))

        assert out["task_id"] == "task_001"
        assert out["run_id"] == "run_1"
        assert out["outcome"] == "fail"
        assert out["task"] == "Fix the MCP server"
        assert len(out["transitions"]) == 2
        t1, t2 = out["transitions"]
        assert t1["k"] == 1 and t1["source_steps"] == [0]
        assert t1["skills_used"] == ["mcp-builder"]
        assert t1["files_read"] == ["SKILL.md"]
        # Second transition merges steps 1 and 2: union of their sources.
        assert t2["k"] == 2 and t2["source_steps"] == [1, 2]
        assert t2["skills_used"] == ["mcp-builder"]
        assert t2["files_read"] == ["reference/node_mcp_server.md"]

    def test_out_of_range_source_step_raises(self, tmp_path):
        (tmp_path / "abstract.txt").write_text("prompt body")
        payload = {
            "transitions": [
                {
                    "state_before": "s",
                    "action": "a",
                    "state_after": "s2",
                    "source_steps": [5],
                }
            ]
        }
        with pytest.raises(ValueError):
            abstract_run(RAW, prompt_dir=tmp_path, client=_chat_client(payload))


class TestClusterActions:
    def _runs(self, actions_per_run):
        return [
            {
                "task_id": f"task_{i}",
                "run_id": f"run_{i}",
                "outcome": "fail",
                "transitions": [
                    {"k": j + 1, "action": a}
                    for j, a in enumerate(actions)
                ],
            }
            for i, actions in enumerate(actions_per_run)
        ]

    def test_synonymous_actions_share_id_across_runs(self):
        runs = self._runs(
            [["open the readme", "run pytest"], ["read the readme", "run pytest"]]
        )
        client = _embedding_client(similar_pairs=[("open the readme", "read the readme")])
        mapping = cluster_actions(runs, client=client)

        assert mapping["open the readme"] == mapping["read the readme"]
        assert mapping["run pytest"] != mapping["open the readme"]
        # Same action id applied in place to every run's transitions.
        assert runs[0]["transitions"][0]["action_id"] == mapping["open the readme"]
        assert runs[1]["transitions"][0]["action_id"] == mapping["read the readme"]
        assert runs[0]["transitions"][0]["action_text"] == "open the readme"
        assert runs[1]["transitions"][0]["action_text"] == "read the readme"
        # Original action field preserved.
        assert runs[0]["transitions"][0]["action"] == "open the readme"

    def test_single_action_run(self):
        runs = self._runs([["only action"]])
        client = _embedding_client(similar_pairs=[])
        mapping = cluster_actions(runs, client=client)
        assert mapping == {"only action": "act_001"}
        assert runs[0]["transitions"][0]["action_id"] == "act_001"

    def test_empty_input(self):
        assert cluster_actions([]) == {}
