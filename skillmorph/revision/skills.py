"""Skill-tree IO helpers shared by the revision stages.

A skill set lives under `skill_dir` as `skill_dir/<skill>/<artifact>`; artifact
paths may nest (`reference/node_mcp_server.md`). Files are addressed everywhere
by that relative path.
"""

import shutil
from pathlib import Path


def read_skill_tree(skill_dir):
    """Read every file under skill_dir into {relative_path: content}."""
    skill_dir = Path(skill_dir)
    return {
        str(path.relative_to(skill_dir)): path.read_text()
        for path in sorted(skill_dir.rglob("*"))
        if path.is_file()
    }


def copy_skill_tree(skill_dir, output_dir):
    """Copy the input skill tree to output_dir; the input is never modified."""
    shutil.copytree(skill_dir, output_dir, dirs_exist_ok=True)


def write_artifact(output_dir, skill, artifact, content):
    """Write one artifact under output_dir/<skill>/<artifact>."""
    path = Path(output_dir) / skill / artifact
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def skill_overview(files):
    """Per-skill SKILL.md text plus artifact list, for the localization prompt."""
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
    """Prefix each line with its 1-based line number for line-range citations."""
    return "\n".join(f"{i:4d}| {line}" for i, line in enumerate(content.splitlines(), 1))
