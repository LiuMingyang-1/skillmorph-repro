"""演化各阶段共用的可调参数。"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "gpt-4o")

EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://api.openai.com/v1")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

TEMPERATURE = 0.0
MAX_TOKENS = 8192

# 每个循环中每项任务的运行次数（论文中 m=3）；首轮暂不涉及，但保留
# 作为后续阶段的文档默认值。
RUNS_PER_TASK = 3

# 判断某次动作是否引入错误时所用的上下文窗口（动作前后各取若干步）。
# （论文中为第 k 步前后各 h 步）。
ERROR_WINDOW = 3

# 传递给编辑位置定位阶段的前 n 个可疑动作（论文中为前 10 个）。
TOP_N_SUSPICIOUS = 10

# 用于合并同义动作的层次聚类截断阈值。
CLUSTER_DISTANCE = 0.5
