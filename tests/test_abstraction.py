"""使用 fake LLM 和嵌入客户端测试 skillmorph.abstraction，不访问网络。"""

import json
import math
from types import SimpleNamespace

import pytest

from skillmorph.abstraction import abstract_run, cluster_actions


def _chat_client(payload):
    """fake OpenAI 客户端；其 chat.completions.create 会返回 `payload`。"""
    message = SimpleNamespace(content=json.dumps(payload))
    completions = SimpleNamespace(
        create=lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=message)])
    )
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def _vec(text, dims):
    """确定性的伪嵌入：根据字符编码生成缩放后的单位向量。"""
    v = [0.0] * dims
    for i, ch in enumerate(text):
        v[i % dims] += (ord(ch) % 17) / 17.0
    return v


def _embedding_client(similar_pairs):
    """对于 `similar_pairs` 中的文本，fake 客户端会让它们共用向量；其他文本使用不同向量。

    similar_pairs：由 (text_a, text_b) 组成的列表；每对文本映射到同一个向量，
    因此余弦距离为 0。不属于任何一对的文本会映射到各自唯一的向量轴。
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
        # 第二个状态转移合并步骤 1 和 2：来源取两者的并集。
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
        # 相同的动作 ID 原地应用到每次运行的状态转移中。
        assert runs[0]["transitions"][0]["action_id"] == mapping["open the readme"]
        assert runs[1]["transitions"][0]["action_id"] == mapping["read the readme"]
        assert runs[0]["transitions"][0]["action_text"] == "open the readme"
        assert runs[1]["transitions"][0]["action_text"] == "read the readme"
        # 保留原始 action 字段。
        assert runs[0]["transitions"][0]["action"] == "open the readme"

    def test_single_action_run(self):
        runs = self._runs([["only action"]])
        client = _embedding_client(similar_pairs=[])
        mapping = cluster_actions(runs, client=client)
        assert mapping == {"only action": "act_001"}
        assert runs[0]["transitions"][0]["action_id"] == "act_001"

    def test_empty_input(self):
        assert cluster_actions([]) == {}
