"""Tunable parameters shared by the evolution stages."""

MODEL = "gpt-4o"
TEMPERATURE = 0.0
MAX_TOKENS = 8192

# Runs per task per loop (paper: m=3); out-of-scope for round one but kept as
# the documented default for later stages.
RUNS_PER_TASK = 3

# Context window (steps on each side) for judging whether an action occurrence
# in a successful run introduced an error (paper: h steps before/after step k).
ERROR_WINDOW = 3

# Top-n suspicious actions passed to edit-site localization (paper: top-10).
TOP_N_SUSPICIOUS = 10

# Hierarchical-clustering cut threshold used to merge synonymous actions.
CLUSTER_DISTANCE = 0.5
