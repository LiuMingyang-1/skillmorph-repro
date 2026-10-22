"""Minimal CLI: ``uv run python -m skillmorph experiments/exp_001``."""

from __future__ import annotations

import argparse
import json

from .pipeline import run_experiment


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m skillmorph",
        description=(
            "Run one SkillMorph loop over an experiment directory "
            "(data/trajectories.json + prompts/ + skills/ -> rounds/round_001)."
        ),
    )
    parser.add_argument("experiment", help="path to the experiment directory")
    args = parser.parse_args(argv)
    summary = run_experiment(args.experiment)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
