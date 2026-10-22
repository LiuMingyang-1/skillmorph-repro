"""Revision proposal generation (paper 4.3).

One proposal per edit site. The site contents, localization rationale, action
evidence, and occurrence contexts are all inside edit_site, so this is a
single self-contained LLM call.
"""

import json

from ..llm import chat_json
from .prompts import load_prompt


def propose(edit_site, client=None, *, prompt_dir):
    """Generate a revision proposal for one edit_site.

    Returns {action_id, edits: [{skill, artifact, lines, change}], rationale}.
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
