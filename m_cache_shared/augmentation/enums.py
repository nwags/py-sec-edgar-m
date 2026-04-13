from __future__ import annotations

from typing import Literal


AugmentationType = Literal["entity_tagging", "temporal_expression_tagging"]
ProducerKind = Literal["llm", "rules", "hybrid", "manual"]
RunStatus = Literal["queued", "running", "completed", "failed", "deferred", "skipped"]

__all__ = ["AugmentationType", "ProducerKind", "RunStatus"]
