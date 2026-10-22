"""使用 LLM 判断某次动作出现是否引入了错误。

按照论文 §4.2，只检查成功运行。对每个状态转移 k，向 LLM 展示其前后
`ERROR_WINDOW` 步的窗口，由 LLM 判断该动作是否引入错误状态（未解决的错误或
未通过验证），而不是仅仅暴露已有错误。失败运行不作判断：其中的每个动作
直接计入失败覆盖。
"""

from pathlib import Path

from .. import config
from ..llm import chat_json


def _load_prompt(prompt_dir: Path) -> str:
    return (prompt_dir / "judge_error.txt").read_text()


def _window(transitions: list[dict], k: int) -> tuple[list[dict], int]:
    """返回第 k 步（索引从 0 开始）前后 ERROR_WINDOW 步内的状态转移，
    并返回首个转移的原始索引。
    """
    lo = max(0, k - config.ERROR_WINDOW)
    hi = min(len(transitions), k + config.ERROR_WINDOW + 1)
    return transitions[lo:hi], lo


def _format_context(transitions: list[dict], offset: int = 0) -> str:
    lines = []
    for i, t in enumerate(transitions):
        action = t.get("action_text") or t.get("action", "")
        lines.append(
            f"step {offset + i}: action={action!r}\n"
            f"  state_before: {t.get('state_before', '')}\n"
            f"  state_after: {t.get('state_after', '')}"
        )
    return "\n".join(lines)


def mark_errors(run: dict, *, prompt_dir, client=None) -> dict:
    """为成功运行中的每条状态转移标记 `introduces_error`。

    修改副本：返回新的运行字典，并为每条状态转移设置
    `introduces_error`（bool）和 `error_reason`（str）。如果运行结果不是
    "success"，则抛出 ValueError；失败运行无需判断（其中所有动作都计入失败覆盖）。
    """
    if run.get("outcome") != "success":
        raise ValueError(
            f"mark_errors only applies to successful runs, got {run.get('outcome')!r}"
        )
    template = _load_prompt(Path(prompt_dir))
    transitions = run["transitions"]
    out = dict(run)
    out_transitions = []
    for k, transition in enumerate(transitions):
        window, offset = _window(transitions, k)
        prompt = template.format(
            context=_format_context(window, offset),
            k=k,
            action=transition.get("action_text") or transition.get("action", ""),
        )
        result = chat_json(
            [{"role": "user", "content": prompt}],
            client=client,
        )
        t = dict(transition)
        t["introduces_error"] = result["introduces_error"]
        t["error_reason"] = str(result.get("reason", ""))
        out_transitions.append(t)
    out["transitions"] = out_transitions
    return out
