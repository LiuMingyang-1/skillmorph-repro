"""使用 fake LLM 客户端测试 mark_errors（不访问网络）。"""

import json

import pytest

from skillmorph import config
from skillmorph.attribution import mark_errors


def _run(task_id, run_id, outcome, steps):
    """steps：由 (action_id, action_text) 组成的列表。"""
    return {
        "task_id": task_id,
        "run_id": run_id,
        "outcome": outcome,
        "transitions": [
            {
                "k": i + 1,
                "state_before": f"s{i}",
                "action_id": aid,
                "action_text": text,
                "state_after": f"s{i+1}",
            }
            for i, (aid, text) in enumerate(steps)
        ],
    }


class _FakeCompletions:
    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []

    def create(self, *, model, messages, temperature, max_tokens, **kwargs):
        self.requests.append(messages)
        answer = self.answers.pop(0)

        class _Choice:
            class message:
                content = json.dumps(answer)

        class _Resp:
            choices = [_Choice()]

        return _Resp()


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeClient:
    """提供 chat.completions.create 接口的最简 OpenAI 兼容替身。"""

    def __init__(self, answers):
        self.chat = _FakeChat(_FakeCompletions(answers))


def test_mark_errors_calls_llm_per_occurrence(tmp_path):
    (tmp_path / "judge_error.txt").write_text(
        "ctx:\n{context}\njudge step {k} {action}\n"
    )
    run = _run("t", "r", "success", [("act_1", "do a"), ("act_2", "do b")])
    client = FakeClient(
        [
            {"introduces_error": True, "reason": "broke it"},
            {"introduces_error": False, "reason": "fine"},
        ]
    )
    out = mark_errors(run, prompt_dir=tmp_path, client=client)
    assert [t["introduces_error"] for t in out["transitions"]] == [True, False]
    assert out["transitions"][0]["error_reason"] == "broke it"
    # 原始运行数据保持不变。
    assert "introduces_error" not in run["transitions"][0]
    assert len(client.chat.completions.requests) == 2


def test_mark_errors_window_excludes_distant_steps(tmp_path):
    (tmp_path / "judge_error.txt").write_text("{context}\n--> {k} {action}\n")
    h = config.ERROR_WINDOW
    steps = [(f"act_{i}", f"a{i}") for i in range(2 * h + 3)]
    run = _run("t", "r", "success", steps)
    answers = [{"introduces_error": False, "reason": ""} for _ in steps]
    client = FakeClient(answers)
    mark_errors(run, prompt_dir=tmp_path, client=client)
    # 判断中间步骤时，只展示前后各 ERROR_WINDOW 步的窗口。
    mid = h + 1
    ctx = client.chat.completions.requests[mid][0]["content"]
    assert f"a{mid - h}" in ctx
    assert f"a{mid + h}" in ctx
    assert f"a{mid + h + 1}" not in ctx


def test_mark_errors_late_target_step_numbers_match(tmp_path):
    """长轨迹（>2h+1）中动作重复出现：上下文窗口中显示的步骤号必须是原始的、
    从 0 开始的状态转移索引，这样被判断的步骤 k 才能与显示的上下文对应。
    """
    h = config.ERROR_WINDOW
    (tmp_path / "judge_error.txt").write_text("{context}\n--> {k} {action}\n")
    n = 2 * h + 5
    # 被判断的动作文本重复出现；将 k 设在末尾附近，以覆盖
    # 左侧窗口被截断的情况（offset > 0）。
    steps = [("act_1", "same action") for _ in range(n)]
    run = _run("t", "r", "success", steps)
    answers = [{"introduces_error": False, "reason": ""} for _ in steps]
    client = FakeClient(answers)
    mark_errors(run, prompt_dir=tmp_path, client=client)

    k = n - 1  # 最后一步；窗口范围为 n-1-h 到 n-1。
    content = client.chat.completions.requests[k][0]["content"]
    ctx, target = content.split("-->")
    assert target.strip().startswith(str(k))
    # 上下文首尾行保留原始索引，而不是相对于窗口的
    # 0 起始索引。
    assert f"step {k - h}:" in ctx
    assert f"step {k}:" in ctx
    assert f"step {k - h - 1}:" not in ctx
    assert "step 0:" not in ctx


def test_mark_errors_rejects_failed_run(tmp_path):
    (tmp_path / "judge_error.txt").write_text("{context} {k} {action}")
    run = _run("t", "r", "fail", [("act_1", "x")])
    with pytest.raises(ValueError):
        mark_errors(run, prompt_dir=tmp_path, client=FakeClient([]))
