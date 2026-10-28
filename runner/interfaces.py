"""数据集与方法接口约定。

编排器（``runner.pipeline``）只依赖这里声明的方法，不含任何数据集
专属分支。新数据集实现 ``DatasetAdapter``，新方法实现 ``Method``
即可接入；模型不属于数据集本体——执行模型是每次执行的显式参数
（``agent`` dict，数据集自行解释，如 SWE 适配的 agent-cmd /
agent-config-json / trajectory-container-path），分析/修订模型由
Method 的调用方注入（SkillMorph 是 ``client``）。

数据集接口以「一次（task, skill 版本）运行」为单位：``prepare_run``
登记环境，``execute`` 执行 + 判分，``export_trajectory`` 单独导出
正式轨迹（编排器只在 before 阶段调用），``cleanup`` 释放环境。证据
不足的 run 记 ``outcome == "invalid"``（三态 success/fail/invalid，
reason 附带），由编排器剔除而不是当作普通失败喂给方法。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class DatasetAdapter(Protocol):
    """一次（task × skill 版本 × run）执行单元的最小契约。

    实现方持有数据集目录，每次调用都返回普通 dict（可 JSON 序列化），
    并把执行/判分/轨迹产物落在调用方给的 ``run_dir`` 下。
    """

    def list_tasks(self, cfg: dict) -> list[str]:
        """按数据集配置返回可执行 task_id 列表（如 family 过滤）。"""
        ...

    def prepare_run(self, task_id: str, skill_dir: Path,
                    run_dir: Path, cfg: dict) -> None:
        """登记一次运行：task/skills/env 身份在此冻结进 run_dir。

        ``skill_dir`` 是本次注入的完整 Skill 树（before 或 after），
        ``run_dir`` 由编排器分配且尚不存在——实现方创建并写登记文件。
        未核验的输入（空 skill 树、非 ready 任务）直接抛错。
        """
        ...

    def execute(self, run_dir: Path, agent: dict) -> dict:
        """在已登记的环境执行 agent 并判分，返回结果摘要。

        ``agent`` 是执行器显式配置（不含数据集语义）。返回至少：
        ``outcome``（success/fail/invalid）、``reason``、可选
        ``evaluation``（判分明细）。数据集明确识别的环境/执行/判分
        证据问题记 ``invalid``，不得当普通 fail 返回；未识别的异常
        原样抛出，由编排器中断实验。
        """
        ...

    def export_trajectory(self, run_dir: Path, agent: dict) -> dict:
        """导出正式轨迹（{task_id, run_id, task, outcome, steps}）。

        数据不足（无真实日志、判分无效）时抛错——编排器对导出异常
        与执行异常同等处理：cleanup 后原样上抛中断实验，不产出
        伪造轨迹、不静默降级为 invalid。
        """
        ...

    def cleanup(self, run_dir: Path, cfg: dict) -> None:
        """释放本 run 的环境资源（容器等），保留 run_dir 产物。

        编排器在 try/finally 中每 run 恰好调用一次（含 execute/export
        抛错的路径）；实现方不需额外提供 reset——after 阶段的「重置」
        语义由编排器用独立 run_dir 重新 prepare 达成。
        """
        ...


class Method(Protocol):
    """轨迹 → 修订后 Skill 的方法契约（单轮、无历史）。"""

    def revise(self, trajectories: list[dict], skill_dir: Path,
               output_dir: Path, cfg: dict) -> dict:
        """对输入 Skill 树做一轮修订，结果写入 ``output_dir``。

        ``trajectories`` 只含原始 Skill 版本下判分为 success/fail 的
        run（invalid 已被编排器剔除）。输入树永不修改；返回结构化摘要
        （selected/rejected/diff 等，方法自定），且必须含
        ``skills_after``——修订后 Skill 树的绝对路径，after 阶段据此
        重新 prepare。
        """
        ...
