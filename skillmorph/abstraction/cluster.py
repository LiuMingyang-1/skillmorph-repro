"""通过嵌入和聚类统一不同运行中的同义动作文本。

对抽象运行中每个不同的 `action` 文本生成嵌入，在 CLUSTER_DISTANCE 处
截断层次聚类，并为每个聚类分配一个 action_id。映射覆盖批次中的全部运行，
因此相同的 action_id 可跨任务和运行进行比较。
"""

from __future__ import annotations

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

from .. import config, llm


def _embed(texts: list[str], client) -> np.ndarray:
    response = client.embeddings.create(model=config.EMBEDDING_MODEL, input=texts)
    return np.array([d.embedding for d in response.data], dtype=float)


def cluster_actions(abstracted_runs: list[dict], client=None) -> dict:
    """原地为所有状态转移分配统一的动作 ID。

    对每条状态转移设置 `action_id`，并将原始 `action` 文本复制到
    `action_text`（`action` 字段本身保持不变）。返回
    {action_text: action_id} 映射。
    """
    texts = sorted(
        {tr["action"] for run in abstracted_runs for tr in run["transitions"]}
    )
    if not texts:
        return {}

    if len(texts) == 1:
        labels = [1]
    else:
        vectors = _embed(texts, client or llm.get_embedding_client())
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
