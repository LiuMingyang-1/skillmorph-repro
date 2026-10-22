"""Unify synonymous action texts across runs via embedding + clustering.

Embeds every distinct `action` string appearing in the abstracted runs,
cuts a hierarchical clustering at CLUSTER_DISTANCE, and assigns one
action_id per cluster. The mapping covers all runs in the batch, so the
same action_id is comparable across tasks and runs.
"""

from __future__ import annotations

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

from .. import config, llm

# Embedding model for action-text comparison. The paper does not specify
# one; this constant keeps the choice local to the abstraction module.
EMBEDDING_MODEL = "text-embedding-3-small"


def _embed(texts: list[str], client) -> np.ndarray:
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return np.array([d.embedding for d in response.data], dtype=float)


def cluster_actions(abstracted_runs: list[dict], client=None) -> dict:
    """Assign unified action ids to all transitions, in place.

    For each transition, sets `action_id` and copies the original `action`
    string into `action_text` (the `action` field itself is left untouched).
    Returns the {action_text: action_id} mapping.
    """
    texts = sorted(
        {tr["action"] for run in abstracted_runs for tr in run["transitions"]}
    )
    if not texts:
        return {}

    if len(texts) == 1:
        labels = [1]
    else:
        vectors = _embed(texts, client or llm.get_client())
        z = linkage(pdist(vectors, metric="cosine"), method="average")
        labels = fcluster(z, t=config.CLUSTER_DISTANCE, criterion="distance")

    mapping = {
        text: f"act_{label:03d}" for text, label in zip(texts, labels)
    }
    for run in abstracted_runs:
        for tr in run["transitions"]:
            tr["action_text"] = tr["action"]
            tr["action_id"] = mapping[tr["action"]]
    return mapping
