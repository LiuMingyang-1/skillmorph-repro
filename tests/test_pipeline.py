"""对 skillmorph.pipeline 进行离线端到端测试。

一个脚本化的 fake 客户端会响应流水线发出的所有 LLM 调用，包括抽象、逐次动作
错误判断、定位、提案和评估；它还会提供确定性嵌入，将一对同义动作文本合并。
测试不访问网络，也不需要 API key。夹具数据和 fake 客户端位于 pipeline_fixture.py。

下面断言的所有评分、选择结果和 diff 都由脚本回复预设，用于验证调用链路和磁盘
产物，而不代表真实模型会产生相同结果。
"""

import json
from pathlib import Path

import pytest

from skillmorph.pipeline import run_experiment
from skillmorph import llm

from pipeline_fixture import (
    ABSTRACTIONS,
    ABSTRACTIONS_ALL_SUCCESS,
    DB_MD,
    NEW_DB_MD,
    PROMPTS,
    RUNS,
    RUNS_ALL_SUCCESS,
    SKILL_MD,
    FakePipelineClient,
    make_experiment,
    tree_snapshot,
)


def _read_json(path):
    return json.loads(Path(path).read_text())


def test_full_loop_writes_all_artifacts_and_revises(tmp_path):
    exp = make_experiment(tmp_path, RUNS)
    before_tree = tree_snapshot(exp / "skills")
    client = FakePipelineClient(ABSTRACTIONS)
    summary = run_experiment(exp, client=client)

    rnd = exp / "runs" / "run_001"
    # 输入快照。
    assert (rnd / "prompts" / "abstract.txt").read_text() == (
        PROMPTS / "abstract.txt"
    ).read_text()
    assert {p.name for p in (rnd / "trajectories").glob("*.json")} == {
        "t1__r1.json", "t1__r2.json", "t2__r1.json", "t2__r2.json"
    }
    assert (rnd / "skills_before" / "sqlite-memory" / "reference"
            / "connections.md").read_text() == DB_MD

    # 分析结果：抽象阶段保留了 task、run 和 outcome；聚类阶段合并了同义动作。
    runs = _read_json(rnd / "analysis" / "abstracted_runs.json")
    assert {r["outcome"] for r in runs} == {"fail", "success"}
    assert runs[0]["transitions"][0]["skills_used"] == ["sqlite-memory"]
    action_map = _read_json(rnd / "analysis" / "action_map.json")
    assert (action_map["open second in-memory connection"]
            == action_map["open a second in-memory connection"])
    ranked = _read_json(rnd / "analysis" / "ranking.json")
    top = ranked[0]
    # 测试夹具预设：N- = 3（两次失败运行，加上一次预设的
    # t2/r2 中引入错误的动作出现），N+ = 0，因此得分为 1.0。
    assert top["action_text"] == "open second in-memory connection"
    assert top["n_fail"] == 3 and top["n_succ"] == 0
    assert top["score"] == pytest.approx(1.0)  # 计算为 3 / sqrt(3 * 3)。
    cov = _read_json(rnd / "analysis" / "coverage.json")
    # 在其他运行中，同一动作也同时出现正常和异常情况。
    users = cov["t2"]["actions"][action_map[
        "create table users via connection A"]]
    assert users["n_fail"] == 1 and users["n_succ"] == 1

    # 修订阶段：只有第二次连接相关的两个动作被定位到编辑位置。
    sites = _read_json(rnd / "revision" / "edit_sites.json")
    located = {s["action_id"]: s for s in sites if s["locations"]}
    assert set(located) == {top["action_id"],
                            action_map["query documents via the second connection"]}
    proposals = _read_json(rnd / "revision" / "proposals.json")
    assert {p["action_id"] for p in proposals} == set(located)
    # 每条修订提案都必须包含编辑位置，让评估器能够看到证据。
    for p in proposals:
        assert p["edit_site"]["action_id"] == p["action_id"]
        assert p["edit_site"]["evidence"]["fail_runs"]
    evaluation = _read_json(rnd / "revision" / "evaluation.json")
    assert set(evaluation["selected"]) == set(located)
    assert evaluation["rejected"] == []
    diff_bytes = (rnd / "revision" / "skills.diff").read_bytes()
    assert b"\r\n" not in diff_bytes
    diff = diff_bytes.decode("utf-8")
    assert "a/sqlite-memory/reference/connections.md" in diff
    assert "Open a new connection per operation." in diff

    # 评估器收到的提示中包含了具体证据
    # （score、fail_runs、n_fail）和动作出现时的上下文，而不只是 ID。
    eval_request = next(
        r for r in client.requests if "evaluating revision proposals" in r
    )
    ctx = json.JSONDecoder().raw_decode(
        eval_request[eval_request.index('{"proposals"'):]
    )[0]["proposals"]
    first = next(p for p in ctx if p["action_id"] == top["action_id"])
    assert first["evidence"]["score"] == pytest.approx(1.0)
    assert first["evidence"]["fail_runs"] == ["t1/r1", "t2/r1", "t2/r2"]
    assert first["evidence"]["n_fail"] == 3
    assert first["occurrences"]
    assert any(
        "in-memory connection" in o["action"] for o in first["occurrences"]
    )
    # 评估器看到的每条提案都带有证据和动作出现记录。
    for p in ctx:
        assert p["evidence"]["fail_runs"] or p["evidence"]["succ_runs"]
        assert p["occurrences"]

    # 修订后的 Skill 目录树；输入保持不变。
    assert (rnd / "skills_after" / "sqlite-memory" / "reference"
            / "connections.md").read_text() == NEW_DB_MD
    assert (rnd / "skills_after" / "sqlite-memory"
            / "SKILL.md").read_text() == SKILL_MD
    assert tree_snapshot(exp / "skills") == before_tree

    assert summary["run"] == "run_001"
    assert summary["runs"] == 4
    assert set(summary["selected"]) == set(located)
    assert summary["diff_empty"] is False
    assert _read_json(rnd / "analysis" / "summary.json") == summary


def test_no_failure_coverage_leaves_skills_unchanged(tmp_path):
    exp = make_experiment(tmp_path, RUNS_ALL_SUCCESS)
    client = FakePipelineClient(ABSTRACTIONS_ALL_SUCCESS)
    summary = run_experiment(exp, client=client)

    rnd = exp / "runs" / "run_001"
    assert _read_json(rnd / "analysis" / "ranking.json") == []
    assert _read_json(rnd / "revision" / "proposals.json") == []
    evaluation = _read_json(rnd / "revision" / "evaluation.json")
    assert evaluation["selected"] == [] and evaluation["rejected"] == []
    assert (rnd / "revision" / "skills.diff").read_text() == ""
    # skills_after 是输入目录树的干净副本。
    after = (rnd / "skills_after" / "sqlite-memory" / "reference"
             / "connections.md").read_text()
    assert after == DB_MD
    # 完全没有调用 localize、propose 或 evaluate。
    assert not any("Mode:" in r for r in client.requests)
    assert summary["suspicious_actions"] == [] and summary["diff_empty"]


def test_consecutive_runs_keep_separate_directories(tmp_path):
    exp = make_experiment(tmp_path, RUNS)
    summary1 = run_experiment(exp, client=FakePipelineClient(ABSTRACTIONS))
    first_snapshot = tree_snapshot(exp / "runs" / "run_001")
    summary2 = run_experiment(exp, client=FakePipelineClient(ABSTRACTIONS))

    assert summary1["run"] == "run_001" and summary2["run"] == "run_002"
    assert (exp / "runs" / "run_001").is_dir()
    assert (exp / "runs" / "run_002").is_dir()
    # 第二次运行完整保留了第一次的产物。
    assert tree_snapshot(exp / "runs" / "run_001") == first_snapshot


def test_next_run_number_skips_gaps_and_stray_entries(tmp_path):
    exp = make_experiment(tmp_path, RUNS_ALL_SUCCESS)
    runs_dir = exp / "runs"
    runs_dir.mkdir()
    (runs_dir / "run_001").mkdir()
    (runs_dir / "run_003").mkdir()  # 编号空洞：run_002 缺省
    (runs_dir / "notes.txt").write_text("unrelated entry")
    (runs_dir / "run_004.txt").write_text("not a directory")

    summary = run_experiment(exp, client=FakePipelineClient(ABSTRACTIONS_ALL_SUCCESS))
    assert summary["run"] == "run_004"
    assert (runs_dir / "run_004" / "analysis" / "summary.json").is_file()
    assert not list((runs_dir / "run_001").iterdir())  # 已有目录未被写入


def test_refuses_to_overwrite_existing_run_dir(tmp_path, monkeypatch):
    from skillmorph import pipeline

    exp = make_experiment(tmp_path, RUNS_ALL_SUCCESS)
    runs_dir = exp / "runs"
    runs_dir.mkdir()
    monkeypatch.setattr(pipeline, "_next_run_number", lambda runs_dir: 1)

    run_experiment(exp, client=FakePipelineClient(ABSTRACTIONS_ALL_SUCCESS))
    with pytest.raises(FileExistsError):
        run_experiment(exp, client=FakePipelineClient(ABSTRACTIONS_ALL_SUCCESS))


def test_raw_dir_restored_on_success(tmp_path):
    exp = make_experiment(tmp_path, RUNS_ALL_SUCCESS)
    llm.set_raw_dir(None)
    run_experiment(exp, client=FakePipelineClient(ABSTRACTIONS_ALL_SUCCESS))
    assert llm._raw_dir is None

    custom = tmp_path / "custom-raw"
    llm.set_raw_dir(custom)
    run_experiment(exp, client=FakePipelineClient(ABSTRACTIONS_ALL_SUCCESS))
    assert llm._raw_dir == custom
    llm.set_raw_dir(None)


def test_raw_dir_restored_on_failure_and_dump_written(tmp_path, monkeypatch):
    exp = make_experiment(tmp_path, RUNS)
    client = FakePipelineClient(ABSTRACTIONS)
    original = client.chat.completions.create
    bad = '{\n"说明": "invalid \\x"}'
    proposal_calls = []

    def respond(**kwargs):
        text = "\n".join(m["content"] for m in kwargs["messages"])
        response = original(**kwargs)
        if "writing a revision proposal" in text:
            proposal_calls.append(text)
            response.choices[0].message.content = bad
        return response

    monkeypatch.setattr(client.chat.completions, "create", respond)
    custom = tmp_path / "custom-raw"
    llm.set_raw_dir(custom)
    with pytest.raises(json.JSONDecodeError, match="Invalid"):
        run_experiment(exp, client=client)
    # 异常退出同样恢复调用前的 raw 设置。
    assert llm._raw_dir == custom
    # 失败原文仍写入本次运行的 raw/，而不是调用前的目录。
    dumps = list((exp / "runs" / "run_001" / "raw").glob("response-*.txt"))
    assert len(proposal_calls) == 1
    assert len(dumps) == 1
    assert dumps[0].read_bytes() == bad.encode("utf-8")
    assert (exp / "runs" / "run_001" / "analysis" / "ranking.json").is_file()
    assert not (exp / "runs" / "run_001" / "revision" / "evaluation.json").exists()
    assert not list(custom.glob("response-*.txt"))
    llm.set_raw_dir(None)
