"""Offline end-to-end tests for skillmorph.pipeline.

One scripted fake client answers every LLM call the pipeline makes —
abstraction, per-occurrence error judging, localization, proposal and
evaluation — and serves deterministic embeddings that merge one pair of
synonymous action texts. No network, no API key. Fixture data and the
fake client live in pipeline_fixture.py.

All scores/selections/diffs asserted below are preset by the scripted
replies — they verify the wiring and on-disk artifacts, not what a real
model would produce.
"""

import json
from pathlib import Path

import pytest

from skillmorph.pipeline import run_experiment

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

    rnd = exp / "rounds" / "round_001"
    # Input snapshots
    assert (rnd / "prompts" / "abstract.txt").read_text() == (
        PROMPTS / "abstract.txt"
    ).read_text()
    assert {p.name for p in (rnd / "trajectories").glob("*.json")} == {
        "t1__r1.json", "t1__r2.json", "t2__r1.json", "t2__r2.json"
    }
    assert (rnd / "skills_before" / "sqlite-memory" / "reference"
            / "connections.md").read_text() == DB_MD

    # Analysis: abstraction kept task/run/outcome, clustering merged synonyms.
    runs = _read_json(rnd / "analysis" / "abstracted_runs.json")
    assert {r["outcome"] for r in runs} == {"fail", "success"}
    assert runs[0]["transitions"][0]["skills_used"] == ["sqlite-memory"]
    action_map = _read_json(rnd / "analysis" / "action_map.json")
    assert (action_map["open second in-memory connection"]
            == action_map["open a second in-memory connection"])
    ranked = _read_json(rnd / "analysis" / "ranking.json")
    top = ranked[0]
    # Preset by the fixture: N- = 3 (two failed runs + one scripted
    # error-introducing occurrence in t2/r2), N+ = 0 -> score 1.0.
    assert top["action_text"] == "open second in-memory connection"
    assert top["n_fail"] == 3 and top["n_succ"] == 0
    assert top["score"] == pytest.approx(1.0)  # 3 / sqrt(3 * 3)
    cov = _read_json(rnd / "analysis" / "coverage.json")
    # Same action splits good/bad occurrences across runs elsewhere too.
    users = cov["t2"]["actions"][action_map[
        "create table users via connection A"]]
    assert users["n_fail"] == 1 and users["n_succ"] == 1

    # Revision: only the two second-connection actions got edit sites.
    sites = _read_json(rnd / "revision" / "edit_sites.json")
    located = {s["action_id"]: s for s in sites if s["locations"]}
    assert set(located) == {top["action_id"],
                            action_map["query documents via the second connection"]}
    proposals = _read_json(rnd / "revision" / "proposals.json")
    assert {p["action_id"] for p in proposals} == set(located)
    # Each proposal must carry its edit site so the evaluator sees evidence.
    for p in proposals:
        assert p["edit_site"]["action_id"] == p["action_id"]
        assert p["edit_site"]["evidence"]["fail_runs"]
    evaluation = _read_json(rnd / "revision" / "evaluation.json")
    assert set(evaluation["selected"]) == set(located)
    assert evaluation["rejected"] == []
    diff = (rnd / "revision" / "skills.diff").read_text()
    assert "a/sqlite-memory/reference/connections.md" in diff
    assert "Open a new connection per operation." in diff

    # The evaluator prompt actually carried the concrete evidence
    # (score, fail_runs, n_fail) and occurrence contexts — not bare ids.
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
    # Every proposal the evaluator saw carried its evidence + occurrences.
    for p in ctx:
        assert p["evidence"]["fail_runs"] or p["evidence"]["succ_runs"]
        assert p["occurrences"]

    # Revised skill tree; inputs untouched.
    assert (rnd / "skills_after" / "sqlite-memory" / "reference"
            / "connections.md").read_text() == NEW_DB_MD
    assert (rnd / "skills_after" / "sqlite-memory"
            / "SKILL.md").read_text() == SKILL_MD
    assert tree_snapshot(exp / "skills") == before_tree

    assert summary["runs"] == 4
    assert set(summary["selected"]) == set(located)
    assert summary["diff_empty"] is False
    assert _read_json(rnd / "analysis" / "summary.json") == summary

    # No clobbering: a second run on the same experiment refuses to write.
    with pytest.raises(FileExistsError):
        run_experiment(exp, client=FakePipelineClient(ABSTRACTIONS))


def test_no_failure_coverage_leaves_skills_unchanged(tmp_path):
    exp = make_experiment(tmp_path, RUNS_ALL_SUCCESS)
    client = FakePipelineClient(ABSTRACTIONS_ALL_SUCCESS)
    summary = run_experiment(exp, client=client)

    rnd = exp / "rounds" / "round_001"
    assert _read_json(rnd / "analysis" / "ranking.json") == []
    assert _read_json(rnd / "revision" / "proposals.json") == []
    evaluation = _read_json(rnd / "revision" / "evaluation.json")
    assert evaluation["selected"] == [] and evaluation["rejected"] == []
    assert (rnd / "revision" / "skills.diff").read_text() == ""
    # skills_after is a clean copy of the input tree.
    after = (rnd / "skills_after" / "sqlite-memory" / "reference"
             / "connections.md").read_text()
    assert after == DB_MD
    # No localize/propose/evaluate calls were made at all.
    assert not any("Mode:" in r for r in client.requests)
    assert summary["suspicious_actions"] == [] and summary["diff_empty"]
