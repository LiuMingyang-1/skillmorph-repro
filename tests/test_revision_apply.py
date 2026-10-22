"""Evaluate/select/apply tests (offline fake client)."""

import json
import subprocess
from pathlib import Path

import pytest
from conftest import ACTION, PROMPTS, SKILL_A, SKILL_B, FakeClient

from skillmorph.revision import evaluate_and_patch


def snapshot(root):
    return {
        str(p.relative_to(root)): p.read_text()
        for p in sorted(Path(root).rglob("*"))
        if p.is_file()
    }


def _proposals():
    return [
        {
            "action_id": "act_001",
            "rationale": "split in-memory connection loses imported data",
            "edits": [
                {"skill": "builder", "artifact": "reference/db.md",
                 "lines": [3, 3],
                 "change": "use one in-memory connection for imports and queries"},
                {"skill": "builder", "artifact": "SKILL.md",
                 "lines": [9, 9],
                 "change": "checklist: query imported documents"},
            ],
            "evidence": ACTION,
            "occurrences": [],
        },
        {
            "action_id": "act_007",
            "rationale": "weak",
            "edits": [{"skill": "writer", "artifact": "SKILL.md",
                       "lines": [1, 1], "change": "tweak"}],
            "evidence": {"action_id": "act_007", "score": 0.1},
        },
    ]


def test_apply_multi_file_and_preserves_input(skill_dir, tmp_path):
    out = tmp_path / "skills_after"
    new_db = "# db\n\nOpen one shared connection for imports and queries.\n"
    new_skill = SKILL_A + "Query imported documents.\n"
    client = FakeClient(
        json.dumps(
            {
                "selected": ["act_001"],
                "rejected": [{"action_id": "act_007",
                              "reason": "insufficient evidence"}],
                "files": [
                    {"skill": "builder", "artifact": "reference/db.md",
                     "content": new_db},
                    {"skill": "builder", "artifact": "SKILL.md",
                     "content": new_skill},
                ],
            }
        )
    )
    result = evaluate_and_patch(
        _proposals(), skill_dir, client=client,
        prompt_dir=PROMPTS, output_dir=out,
    )

    assert result["selected"] == ["act_001"]
    assert result["rejected"] == [{"action_id": "act_007",
                                   "reason": "insufficient evidence"}]
    assert result["skills_after"] == str(out)

    # cross-file revision applied; rejected proposal's target untouched
    assert (out / "builder" / "reference" / "db.md").read_text() == new_db
    assert (out / "builder" / "SKILL.md").read_text() == new_skill
    assert (out / "writer" / "SKILL.md").read_text() == SKILL_B
    # input preserved verbatim
    assert snapshot(skill_dir) == snapshot(tmp_path / "skills")

    diff = result["diff"]
    assert "a/builder/reference/db.md" in diff
    assert "a/builder/SKILL.md" in diff
    assert "writer" not in diff

    # evidence was forwarded to the evaluator, not a bare action_id
    sent = client.requests[0]["messages"][0]["content"]
    assert '"n_fail": 2' in sent
    assert "npm run build must succeed." in sent


def test_empty_selection_applies_nothing(skill_dir, tmp_path):
    """selected=[] means nothing is written, even if files are returned."""
    out = tmp_path / "skills_after"
    client = FakeClient(
        json.dumps(
            {
                "selected": [],
                "rejected": [{"action_id": "act_001", "reason": "duplicate"},
                              {"action_id": "act_007", "reason": "no evidence"}],
                "files": [{"skill": "builder", "artifact": "SKILL.md",
                           "content": "should never be written"}],
            }
        )
    )
    result = evaluate_and_patch(
        _proposals(), skill_dir, client=client,
        prompt_dir=PROMPTS, output_dir=out,
    )
    assert result["selected"] == []
    assert result["diff"] == ""
    assert snapshot(out) == snapshot(skill_dir)


def test_empty_proposals_no_llm(skill_dir, tmp_path):
    out = tmp_path / "skills_after"
    client = FakeClient()  # any call would raise assertion error
    result = evaluate_and_patch(
        [], skill_dir, client=client, prompt_dir=PROMPTS, output_dir=out
    )
    assert result["selected"] == [] and result["rejected"] == []
    assert result["diff"] == ""
    assert snapshot(out) == snapshot(skill_dir)  # clean copy


def _git_apply(diff, before, tmp_path):
    """Apply `diff` in a temp git repo containing `before`; return file text."""
    repo = tmp_path / "repo"
    (repo / "builder").mkdir(parents=True)
    (repo / "builder" / "SKILL.md").write_text(before)
    run = lambda *args: subprocess.run(
        args, cwd=repo, check=True, capture_output=True, text=True
    )
    run("git", "init", "-q")
    run("git", "add", "-A")
    (repo / "patch.diff").write_text(diff)
    run("git", "apply", "--check", "patch.diff")
    run("git", "apply", "patch.diff")
    return (repo / "builder" / "SKILL.md").read_text()


def _patch_no_eol(skill_dir, tmp_path, before, after):
    (skill_dir / "builder" / "SKILL.md").write_text(before)
    client = FakeClient(
        json.dumps(
            {
                "selected": ["act_001"],
                "rejected": [],
                "files": [{"skill": "builder", "artifact": "SKILL.md",
                           "content": after}],
            }
        )
    )
    return evaluate_and_patch(
        [{"action_id": "act_001", "edits": [], "rationale": "r",
          "evidence": ACTION}],
        skill_dir, client=client,
        prompt_dir=PROMPTS, output_dir=tmp_path / "after",
    )


@pytest.mark.parametrize(
    "before,after",
    [
        ("old guidance", "new guidance"),          # neither side ends with \n
        ("old guidance", "new guidance\n"),        # only before lacks it
        ("old guidance\n", "new guidance"),        # only after lacks it
        ("a\nsame", "b\nsame"),                    # no-eol tail as context
    ],
    ids=["no-eol-both", "no-eol-before", "no-eol-after", "no-eol-context"],
)
def test_diff_without_trailing_newline_git_applies(
    skill_dir, tmp_path, before, after
):
    result = _patch_no_eol(skill_dir, tmp_path, before, after)
    diff = result["diff"]
    if not (before.endswith("\n") and after.endswith("\n")):
        assert "\\ No newline at end of file" in diff
    # the patch applies cleanly and yields the new content byte-for-byte
    assert _git_apply(diff, before, tmp_path) == after
    # applied file on disk is byte-identical to the returned content
    assert (tmp_path / "after" / "builder" / "SKILL.md").read_text() == after
