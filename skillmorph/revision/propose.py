"""生成修订提案（论文 4.3）。

每个编辑位置生成一条提案。编辑位置的内容、定位理由、动作证据和出现上下文
都包含在 edit_site 中，因此只需一次完整的 LLM 调用。
"""

import json

from ..llm import chat_json
from .prompts import load_prompt


def propose(edit_site, client=None, *, prompt_dir):
    """为一个 edit_site 生成修订提案。

    返回 {action_id, edits: [{skill, artifact, lines, change}], rationale}。
    """
    template = load_prompt(prompt_dir, "propose.txt")
    result = chat_json(
        [{"role": "user", "content": template.substitute(
            edit_site_json=json.dumps(edit_site)
        )}],
        client=client,
    )
    return {
        "action_id": edit_site["action_id"],
        "edits": result.get("edits", []),
        "rationale": result.get("rationale", ""),
    }
