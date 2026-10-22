"""归因：标记错误引入、统计覆盖次数并对可疑动作排序。"""

from .coverage import coverage
from .marking import mark_errors
from .ranking import rank

__all__ = ["mark_errors", "coverage", "rank"]
