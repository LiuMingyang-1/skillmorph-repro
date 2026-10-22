"""手工计算覆盖计数和可疑度排序的测试。

夹具包含 2 个任务的 5 次运行，动作出现情况由 fake judge 标记：

  task_001/run_1  失败     act_1 act_1 act_2          -> act_1、act_2 计入失败覆盖
  task_001/run_2  成功     act_1(错误) act_1(正常) act_2(正常)
                                                   -> act_1 同时计入失败和成功覆盖
                                                      （同一次运行、同一动作，
                                                      不同出现情况判断不同），
                                                      act_2 计入成功覆盖
  task_001/run_3  成功     act_1(错误) act_3(正常)   -> act_1 失败覆盖，act_3 成功覆盖
  task_002/run_1  失败     act_3                     -> act_3 计入失败覆盖
  task_002/run_2  成功     act_2(正常)               -> act_2 计入成功覆盖

各任务的计数：
  task_001: act_1 N-=3 N+=1（run_1、run_2、run_3 计入失败；run_2 也计入成功）
            act_2 N-=1 N+=1（run_1 计入失败，run_2 计入成功）
            act_3 N+=1（run_3 计入成功）
            F = 3（run_1、run_2、run_3 都提供了失败覆盖）
  task_002: act_3 N-=1，act_2 N+=1，F = 1（run_1）

跨任务总计（F = 4）：
  act_1: N-=3, N+=1   act_2: N-=1, N+=2   act_3: N-=1, N+=1

评分公式：s(a) = N- / sqrt(F * (N- + N+))（论文公式 9，Ochiai）：
  act_1 = 3/sqrt(4*4) = 0.750000
  act_3 = 1/sqrt(4*2) = 0.353553
  act_2 = 1/sqrt(4*3) = 0.288675
"""

import json
import math

import pytest

from skillmorph.attribution import coverage, rank


def _run(task_id, run_id, outcome, steps):
    """steps：由 (action_id, action_text, introduces_error|None) 组成的列表。"""
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
                **({"introduces_error": err} if err is not None else {}),
            }
            for i, (aid, text, err) in enumerate(steps)
        ],
    }


@pytest.fixture
def runs():
    return [
        _run(
            "task_001", "run_1", "fail",
            [("act_1", "install deps", None),
             ("act_1", "install deps", None),
             ("act_2", "run tests", None)],
        ),
        _run(
            "task_001", "run_2", "success",
            [("act_1", "install deps", True),
             ("act_1", "install deps", False),
             ("act_2", "run tests", False)],
        ),
        _run(
            "task_001", "run_3", "success",
            [("act_1", "install deps", True),
             ("act_3", "edit config", False)],
        ),
        _run(
            "task_002", "run_1", "fail",
            [("act_3", "edit config", None)],
        ),
        _run(
            "task_002", "run_2", "success",
            [("act_2", "run tests", False)],
        ),
    ]


def test_coverage_dedups_repeated_occurrences(runs):
    cov = coverage(runs)
    a1 = cov["task_001"]["actions"]["act_1"]
    # run_1 在失败运行中两次出现 act_1，仍只计一次覆盖。
    assert a1["n_fail"] == 3
    assert a1["fail_runs"] == [
        "task_001/run_1", "task_001/run_2", "task_001/run_3",
    ]
    assert a1["n_succ"] == 1
    assert a1["succ_runs"] == ["task_001/run_2"]


def test_coverage_mixed_occurrences_give_both_coverages(runs):
    cov = coverage(runs)
    a1 = cov["task_001"]["actions"]["act_1"]
    # run_2 中 act_1 有一次引入错误、一次正常，因此失败覆盖和成功覆盖
    # 都会计入（按出现次数判断，并分别去重）。
    assert "task_001/run_2" in a1["fail_runs"]
    assert a1["succ_runs"] == ["task_001/run_2"]


def test_coverage_f_counts_runs_with_any_failure_coverage(runs):
    cov = coverage(runs)
    # task_001：run_1 失败；run_2 和 run_3 中有引入错误的动作。
    assert cov["task_001"]["f"] == 3
    assert cov["task_001"]["fail_runs"] == [
        "task_001/run_1", "task_001/run_2", "task_001/run_3",
    ]
    # task_002：只有 run_1 失败；run_2 中的 act_2 正常。
    assert cov["task_002"]["f"] == 1
    assert cov["task_002"]["fail_runs"] == ["task_002/run_1"]


def test_coverage_success_run_requires_judgment(runs):
    runs[1]["transitions"][0].pop("introduces_error")
    with pytest.raises(ValueError):
        coverage(runs)


def test_coverage_json_serializable(runs):
    json.dumps(coverage(runs))


def test_coverage_rejects_bad_outcome(runs):
    runs[0]["outcome"] = "unknown"
    with pytest.raises(ValueError):
        coverage(runs)


def test_rank_scores_and_order(runs):
    ranked = rank(coverage(runs), abstracted_runs=runs)
    expected = {
        "act_1": 3 / math.sqrt(4 * 4),   # 得分为 0.75。
        "act_3": 1 / math.sqrt(4 * 2),   # 得分为 0.35355。
        "act_2": 1 / math.sqrt(4 * 3),   # 得分为 0.28868。
    }
    assert [r["action_id"] for r in ranked] == ["act_1", "act_3", "act_2"]
    for r in ranked:
        assert r["score"] == pytest.approx(expected[r["action_id"]])


def test_rank_evidence_fields(runs):
    ranked = rank(coverage(runs), abstracted_runs=runs)
    a1 = ranked[0]
    assert a1["n_fail"] == 3 and a1["n_succ"] == 1
    assert a1["fail_runs"] == [
        "task_001/run_1", "task_001/run_2", "task_001/run_3",
    ]
    assert a1["succ_runs"] == ["task_001/run_2"]
    assert a1["tasks"] == ["task_001"]
    assert a1["action_text"] == "install deps"
    json.dumps(ranked)


def test_rank_top_n(runs):
    assert len(rank(coverage(runs), top_n=2)) == 2


def test_rank_excludes_actions_without_failure_coverage(runs):
    ranked = rank(coverage(runs))
    assert all(r["n_fail"] > 0 for r in ranked)


def test_rank_no_failure_coverage_returns_empty():
    run = _run("t", "r", "success", [("act_1", "x", False)])
    assert rank(coverage([run])) == []
