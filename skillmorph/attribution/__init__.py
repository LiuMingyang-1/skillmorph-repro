"""Attribution: error-introduction marking, coverage counts, suspicious ranking."""

from .coverage import coverage
from .marking import mark_errors
from .ranking import rank

__all__ = ["mark_errors", "coverage", "rank"]
