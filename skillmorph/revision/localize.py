"""定位编辑位置（论文 4.3）。

采用两轮逐步缩小范围，而非使用可调用工具的 Agent：首先，LLM 根据概览和记录的
Skill 使用情况选出相关资源；随后读取这些资源的带行号内容，并标注行范围。
定位到的内容会嵌入返回的 edit_site，因此后续 propose() 无需再次访问 Skill 目录树。
不提供回退：LLM 选出的内容会原样使用，空选择也保持为空。
"""

import json

from ..llm import chat_json
from .prompts import load_prompt
from .skills import numbered, read_skill_tree, skill_overview


def _occurrences(action, runs):
    """证据运行中可疑动作出现时的上下文。"""
    wanted = set(action.get("fail_runs", [])) | set(action.get("succ_runs", []))
    out = []
    for run in runs:
        if f"{run['task_id']}/{run['run_id']}" not in wanted:
            continue
        transitions = run["transitions"]
        for k, tr in enumerate(transitions):
            if tr.get("action_id") != action["action_id"]:
                continue
            out.append(
                {
                    "run": f"{run['task_id']}/{run['run_id']}",
                    "outcome": run["outcome"],
                    "step": k,
                    "state_before": tr.get("state_before"),
                    "action": tr.get("action_text") or tr.get("action"),
                    "state_after": tr.get("state_after"),
                    "skills_used": tr.get("skills_used", []),
                    "files_read": tr.get("files_read", []),
                    # mark_errors() 生成的逐次出现判断；失败运行中没有这些判断，
                    # 其中的动作直接计入失败覆盖，
                    # 无需判断；此处的 None 绝不表示动作正常。
                    "introduces_error": tr.get("introduces_error"),
                    "error_reason": tr.get("error_reason"),
                    "prev_action": transitions[k - 1].get("action") if k else None,
                    "next_action": transitions[k + 1].get("action")
                    if k + 1 < len(transitions)
                    else None,
                }
            )
    return out


def _file_hints(action, runs, skills):
    """轨迹中记录为已查阅、且相对于 skill_dir 的资源路径。

    仅作为定位证据传给 LLM；不会并入选中的文件。
    """
    hints = set()
    wanted = set(action.get("fail_runs", [])) | set(action.get("succ_runs", []))
    for run in runs:
        if f"{run['task_id']}/{run['run_id']}" not in wanted:
            continue
        for tr in run["transitions"]:
            used = {s for s in tr.get("skills_used", []) if s in skills}
            hints.update(f"{s}/SKILL.md" for s in used)
            for rel in tr.get("files_read", []):
                hints.add(rel)
                hints.update(f"{s}/{rel}" for s in used)
    return hints


def localize(action, skill_dir, runs, client=None, *, prompt_dir):
    """定位指导某个可疑动作的 Skill 内容。

    返回 edit_site 字典，包含 action_id、locations（skill/artifact/lines/
    content）、rationale、evidence 和使用的动作出现上下文。
    """
    files = read_skill_tree(skill_dir)
    contexts = _occurrences(action, runs)
    hints = _file_hints(action, runs, {rel.split("/", 1)[0] for rel in files})
    evidence = {
        "score": action.get("score"),
        "n_fail": action.get("n_fail"),
        "n_succ": action.get("n_succ"),
        "fail_runs": action.get("fail_runs", []),
        "succ_runs": action.get("succ_runs", []),
        "tasks": action.get("tasks", []),
    }
    payload = {
        "action_id": action["action_id"],
        "action_text": action.get("action_text"),
        "occurrences": contexts,
    }
    consulted = "\n".join(f"- {rel}" for rel in sorted(hints)) or "(none)"
    template = load_prompt(prompt_dir, "localize.txt")
    overview = skill_overview(files)

    first = chat_json(
        [{"role": "user", "content": template.substitute(
            mode="artifacts", action_json=json.dumps(payload),
            skill_overview=overview, candidates=consulted,
        )}],
        client=client,
    )
    if not first["locations"]:
        return {
            "action_id": action["action_id"],
            "locations": [],
            "rationale": first.get("rationale", ""),
            "evidence": evidence,
            "occurrences": contexts,
        }

    # 严格使用 LLM 选中的文件；遇到未知路径时抛出 KeyError。
    selected, seen = [], set()
    for loc in first["locations"]:
        rel = f"{loc['skill']}/{loc['artifact']}"
        if rel not in seen:
            seen.add(rel)
            selected.append((rel, files[rel]))

    numbered_contents = "\n\n".join(
        f"### file: {rel}\n{numbered(content)}" for rel, content in selected
    )
    second = chat_json(
        [{"role": "user", "content": template.substitute(
            mode="lines", action_json=json.dumps(payload),
            skill_overview=overview, candidates=numbered_contents,
        )}],
        client=client,
    )

    locations = []
    for loc in second["locations"]:
        rel = f"{loc['skill']}/{loc['artifact']}"
        locations.append({**loc, "content": files[rel]})
    return {
        "action_id": action["action_id"],
        "locations": locations,
        "rationale": second.get("rationale", "") or first.get("rationale", ""),
        "evidence": evidence,
        "occurrences": contexts,
    }
