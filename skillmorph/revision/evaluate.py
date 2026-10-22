"""评估、选择并应用修订提案（论文 4.3）。

通过一次 CoT 调用，结合每个动作的证据、当前 Skill 内容（检查重复或冲突，以及
是否存在超出证据范围的修改）和依赖被编辑内容的成功运行来评估所有提案。LLM
返回选中和拒绝的 ID，以及每个待修改文件的完整新内容；本模块将输入目录树复制到
output_dir 并仅替换这些文件，因此无需解析补丁，且不会修改输入目录。
只有选中的提案非空时才会应用文件修改。
"""

import difflib
import json

from ..llm import chat_json
from .prompts import load_prompt
from .skills import copy_skill_tree, read_skill_tree, write_artifact


def evaluate_and_patch(proposals, skill_dir, client=None, *, prompt_dir, output_dir):
    """评估提案，并将合并后的修订应用到 output_dir。

    返回 {selected, rejected, diff, skills_after}。每条提案可以携带
    "evidence"/"occurrences" 或内嵌的 "edit_site"；两者都会传递给 LLM，
    确保 LLM 评估 action_id 时始终有相应证据。
    """
    files = read_skill_tree(skill_dir)
    copy_skill_tree(skill_dir, output_dir)

    if not proposals:
        return {
            "selected": [],
            "rejected": [],
            "diff": "",
            "skills_after": str(output_dir),
        }

    context = {
        "proposals": [
            {
                "action_id": p["action_id"],
                "rationale": p.get("rationale", ""),
                "edits": p.get("edits", []),
                "evidence": p.get("evidence")
                or p.get("edit_site", {}).get("evidence"),
                "occurrences": p.get("occurrences")
                or p.get("edit_site", {}).get("occurrences"),
            }
            for p in proposals
        ],
        "skill_contents": [
            {"path": rel, "content": content} for rel, content in files.items()
        ],
    }
    result = chat_json(
        [{"role": "user", "content": load_prompt(
            prompt_dir, "evaluate_select.txt"
        ).substitute(proposals_json=json.dumps(context))}],
        client=client,
    )

    selected = result["selected"]
    if not selected:
        return {
            "selected": [],
            "rejected": result["rejected"],
            "diff": "",
            "skills_after": str(output_dir),
        }

    after = dict(files)
    applied = []
    for entry in result["files"]:
        rel = f"{entry['skill']}/{entry['artifact']}"
        after[rel] = entry["content"]
        applied.append(rel)

    for rel in applied:
        write_artifact(
            output_dir, rel.split("/", 1)[0], rel.split("/", 1)[1], after[rel]
        )

    return {
        "selected": selected,
        "rejected": result["rejected"],
        "diff": _unified_diff(files, after),
        "skills_after": str(output_dir),
    }


NO_EOL = "\\ No newline at end of file"


def _diff_lines(text):
    """为 difflib 拆分内容，并将无行尾标记附加到最后一行。

    如果文件末尾没有换行符，就在最后一行后附加标准标记。无论该行在 hunk 中
    被标记为删除（-）、新增（+）还是上下文，hunk 都能保持格式正确。
    文件内容本身不会被修改。
    """
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n" + NO_EOL + "\n"
    return lines


def _unified_diff(before, after):
    chunks = []
    for rel in sorted(set(before) | set(after)):
        old, new = before.get(rel, ""), after.get(rel, "")
        if old == new:
            continue
        chunks.append(
            "".join(
                difflib.unified_diff(
                    _diff_lines(old),
                    _diff_lines(new),
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                )
            )
        )
    return "\n".join(chunks)
