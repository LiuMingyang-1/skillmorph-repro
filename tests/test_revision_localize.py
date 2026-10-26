"""定位和提案测试（使用离线 fake 客户端）。"""

import json
from pathlib import PureWindowsPath

import pytest
from conftest import ACTION, PROMPTS, RUNS, FakeClient

from skillmorph.revision import evaluate_and_patch, localize, propose
from skillmorph.revision.skills import _relative_protocol_path, read_skill_tree


def _mixed_runs():
    """某个动作同时出现在经过判断的成功运行和未经判断的失败运行中。"""
    return [
        {
            "task_id": "t1",
            "run_id": "ok",
            "outcome": "success",
            "transitions": [
                {
                    "action_id": "act_001",
                    "action_text": "open second in-memory connection",
                    "state_before": "s0",
                    "state_after": "no such table",
                    "introduces_error": True,
                    "error_reason": "creates an isolated empty database",
                    "skills_used": ["builder"],
                    "files_read": ["builder/SKILL.md"],
                },
                {
                    "action_id": "act_999",
                    "action_text": "unrelated step",
                    "state_before": "s1",
                    "state_after": "s2",
                    "introduces_error": False,
                    "error_reason": "",
                },
            ],
        },
        {
            "task_id": "t1",
            "run_id": "bad",
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


_MIXED_ACTION = {
    "action_id": "act_001",
    "action_text": "use a second in-memory connection",
    "score": 0.7,
    "n_fail": 2,
    "n_succ": 1,
    "fail_runs": ["t1/ok", "t1/bad"],
    "succ_runs": ["t1/ok"],
    "tasks": ["t1"],
}

_EMPTY_SITE = {
    "action_id": "act_001",
    "locations": [{"skill": "builder", "artifact": "SKILL.md",
                   "lines": [1, 1], "content": "x"}],
    "rationale": "r",
    "evidence": {"score": 0.7},
}


def test_skill_paths_use_posix_protocol_separators(skill_dir):
    files = read_skill_tree(skill_dir)
    assert "builder/reference/db.md" in files
    assert all("\\" not in path for path in files)

    # Exercise pathlib's Windows path flavor without claiming Windows I/O was run.
    root = PureWindowsPath(r"skill-set")
    nested = PureWindowsPath(r"skill-set\builder\reference\db.md")
    assert _relative_protocol_path(nested, root) == "builder/reference/db.md"


def test_occurrence_error_marks_reach_propose_and_evaluate(
    skill_dir, tmp_path
):
    """mark_errors() 添加的字段会保留，并传递到 localize -> propose -> evaluate 的 prompt 中。"""
    client = FakeClient(json.dumps({"locations": [], "rationale": "none"}))
    site = localize(
        _MIXED_ACTION, skill_dir, _mixed_runs(),
        client=client, prompt_dir=PROMPTS,
    )
    assert len(site["occurrences"]) == 2
    by_run = {o["run"]: o for o in site["occurrences"]}
    assert by_run["t1/ok"]["introduces_error"] is True
    assert by_run["t1/ok"]["error_reason"] == "creates an isolated empty database"
    # 未经判断的失败运行：值为 None，绝不伪造为“正常”。
    assert by_run["t1/bad"]["introduces_error"] is None
    assert by_run["t1/bad"]["error_reason"] is None
    sent = client.requests[0]["messages"][0]["content"]
    assert "creates an isolated empty database" in sent

    client = FakeClient(json.dumps({"edits": [], "rationale": "r"}))
    propose(
        {**_EMPTY_SITE, "occurrences": site["occurrences"]},
        client=client, prompt_dir=PROMPTS,
    )
    assert "creates an isolated empty database" in (
        client.requests[0]["messages"][0]["content"]
    )

    client = FakeClient(
        json.dumps({"selected": [], "rejected": [], "files": []})
    )
    evaluate_and_patch(
        [{"action_id": "act_001", "edits": [], "rationale": "r",
          "occurrences": site["occurrences"]}],
        skill_dir, client=client,
        prompt_dir=PROMPTS, output_dir=tmp_path / "after",
    )
    assert "creates an isolated empty database" in (
        client.requests[0]["messages"][0]["content"]
    )


def test_localize_embeds_contents_and_evidence(skill_dir):
    client = FakeClient(
        json.dumps(
            {
                "locations": [
                    {"skill": "builder", "artifact": "reference/db.md"},
                    {"skill": "builder", "artifact": "SKILL.md"},
                ],
                "rationale": "builder docs govern connections",
            }
        ),
        json.dumps(
            {
                "locations": [
                    {"skill": "builder", "artifact": "reference/db.md",
                     "lines": [3, 3]},
                    {"skill": "builder", "artifact": "SKILL.md",
                     "lines": [5, 5]},
                ],
                "rationale": "no rule for sharing in-memory connections",
            }
        ),
    )
    site = localize(ACTION, skill_dir, RUNS, client=client, prompt_dir=PROMPTS)

    assert site["action_id"] == "act_001"
    assert site["evidence"]["fail_runs"] == ["t1/r1", "t1/r2"]
    assert len(site["occurrences"]) == 2  # 已收集两次运行中的动作出现记录。
    by_artifact = {loc["artifact"]: loc for loc in site["locations"]}
    assert set(by_artifact) == {"reference/db.md", "SKILL.md"}
    assert "connection per operation" in by_artifact["reference/db.md"]["content"]
    assert "npm run build" in by_artifact["SKILL.md"]["content"]
    # 第二次调用包含了选中文件及其编号内容。
    assert "builder/reference/db.md" in client.requests[0]["messages"][0]["content"]
    assert "connection per operation" in client.requests[1]["messages"][0]["content"]


def test_localize_empty_selection_stops_without_fallback(skill_dir):
    """资源选择为空时返回 locations=[]，且不会进行第二次调用。"""
    client = FakeClient(
        json.dumps({"locations": [], "rationale": "nothing relevant"})
    )
    site = localize(ACTION, skill_dir, RUNS, client=client, prompt_dir=PROMPTS)
    assert site["locations"] == []
    assert site["evidence"]["score"] == 0.61
    assert len(client.requests) == 1  # 不启用回退，也不进行第二次调用。


def test_localize_empty_line_locations_stay_empty(skill_dir):
    """第二次调用没有返回定位结果时保持为空，不补填其他内容。"""
    client = FakeClient(
        json.dumps(
            {
                "locations": [{"skill": "builder", "artifact": "SKILL.md"}],
                "rationale": "maybe",
            }
        ),
        json.dumps({"locations": [], "rationale": "on inspection, none"}),
    )
    site = localize(ACTION, skill_dir, RUNS, client=client, prompt_dir=PROMPTS)
    assert site["locations"] == []


def test_localize_unknown_artifact_raises(skill_dir):
    """所选路径不存在时应报错，而不是直接过滤掉。"""
    client = FakeClient(
        json.dumps(
            {
                "locations": [{"skill": "builder", "artifact": "no/such.md"}],
                "rationale": "bogus",
            }
        )
    )
    with pytest.raises(KeyError):
        localize(ACTION, skill_dir, RUNS, client=client, prompt_dir=PROMPTS)


def test_propose_returns_edits():
    edit_site = {
        "action_id": "act_001",
        "locations": [
            {"skill": "builder", "artifact": "reference/db.md",
             "lines": [3, 3], "content": "x"}
        ],
        "rationale": "r",
        "evidence": {"score": 0.61},
        "occurrences": [],
    }
    client = FakeClient(
        json.dumps(
            {
                "edits": [
                    {"skill": "builder", "artifact": "reference/db.md",
                     "lines": [3, 3],
                     "change": "share one in-memory connection"}
                ],
                "rationale": "prevents split in-memory databases",
            }
        )
    )
    proposal = propose(edit_site, client=client, prompt_dir=PROMPTS)
    assert proposal["action_id"] == "act_001"
    assert proposal["edits"][0]["artifact"] == "reference/db.md"
