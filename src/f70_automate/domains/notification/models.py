from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class NotificationMessage:
    title: str
    body: str
    occurred_at: datetime
    tags: dict[str, str] = field(default_factory=dict)
