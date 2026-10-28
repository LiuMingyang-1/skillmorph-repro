"""内置简单 Method：``"copy"``/``"noop"``——原样拷贝 Skill 树。

用于编排/采集通道验证（before/after 用同一棵树重跑），不声称修订；
method.revise 返回 ``selected=[]``，comparison 的 before/after 应
一致（两个独立 run）。
"""

from __future__ import annotations

import shutil
from pathlib import Path


class CopyMethod:
    """原样拷贝 Skill 树的 Method。"""

    def revise(self, trajectories, skill_dir, output_dir, cfg):
        out = Path(output_dir) / "skills_after"
        out.mkdir(parents=True, exist_ok=False)
        shutil.copytree(skill_dir, out, dirs_exist_ok=True)
        return {"trajectories": len(trajectories), "selected": [],
                "rejected": [], "diff": "", "skills_after": str(out)}


def get_method(cfg: dict | None = None) -> CopyMethod:
    return CopyMethod()
