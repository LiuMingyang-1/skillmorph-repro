"""修订阶段共用的 Skill 目录树输入输出辅助函数。

Skill 集合位于 `skill_dir` 下，路径形式为 `skill_dir/<skill>/<artifact>`；资源
路径可以包含子目录（例如 `reference/node_mcp_server.md`）。各处均使用该相对路径
来引用文件。
"""

import shutil
from pathlib import Path


def read_skill_tree(skill_dir):
    """读取 skill_dir 下的所有文件，返回 {relative_path: content}。"""
    skill_dir = Path(skill_dir)
    return {
        str(path.relative_to(skill_dir)): path.read_text()
        for path in sorted(skill_dir.rglob("*"))
        if path.is_file()
    }


def copy_skill_tree(skill_dir, output_dir):
    """将输入 Skill 目录树复制到 output_dir；不修改输入目录。"""
    shutil.copytree(skill_dir, output_dir, dirs_exist_ok=True)


def write_artifact(output_dir, skill, artifact, content):
    """将一个资源文件写入 output_dir/<skill>/<artifact>。"""
    path = Path(output_dir) / skill / artifact
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def skill_overview(files):
    """为定位 prompt 提供每个 Skill 的 SKILL.md 文本和资源列表。"""
    skills = {}
    for rel in files:
        skills.setdefault(rel.split("/", 1)[0], []).append(rel)
    parts = []
    for skill, artifacts in skills.items():
        parts.append(
            f"## skill: {skill}\n"
            f"SKILL.md:\n{files.get(f'{skill}/SKILL.md', '(missing)')}\n"
            "artifacts:\n" + "\n".join(f"- {rel}" for rel in artifacts)
        )
    return "\n\n".join(parts)


def numbered(content):
    """为每行添加从 1 开始的行号，以便引用行范围。"""
    return "\n".join(f"{i:4d}| {line}" for i, line in enumerate(content.splitlines(), 1))
