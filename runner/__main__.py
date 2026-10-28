"""``python -m runner <config.json>``：单轮数据集/方法可替换编排入口。"""

from __future__ import annotations

import argparse
import json

from .pipeline import run_experiment


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m runner",
        description=(
            "Run one dataset/method-agnostic SkillMorph round: "
            "baseline execution -> method revision -> rerun with the "
            "revised skill in a reset environment -> comparison."
        ),
    )
    parser.add_argument("config", help="path to the experiment config JSON")
    args = parser.parse_args(argv)
    summary = run_experiment(args.config)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
