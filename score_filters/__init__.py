"""Deterministic post-LLM safety net filters.

These run *after* the LLM has scored a job and exist to catch mistakes the
prompt failed to enforce (e.g. high-scoring non-US roles despite the LOCATION
HARD GATE in `config.CRITERIA`). Tags produced here are persisted to
`scored_results.rejection_reason` for auditability.
"""

from .auto_reject import auto_reject_reason
from .location_usa import is_usa_location

__all__ = ["auto_reject_reason", "is_usa_location"]
