from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import total_ordering
from typing import Any


@total_ordering
class LogLevel(Enum):
    """ログレベル: DEBUG < INFO < WARNING < ERROR < CRITICAL"""

    DEBUG    = 10
    INFO     = 20
    WARNING  = 30
    ERROR    = 40
    CRITICAL = 50

    def __lt__(self, other: LogLevel) -> bool:
        return self.value < other.value


@dataclass(frozen=True)
class LogEntry:
    """ログエントリ"""

    level: LogLevel
    message: str
    timestamp: datetime
    source: str | None = None
    context: dict[str, Any] | None = None

    def format_simple(self) -> str:
        """シンプルなフォーマット: [LEVEL] HH:MM:SS | message"""
        time_str = self.timestamp.strftime("%H:%M:%S")
        source_part = f" ({self.source})" if self.source else ""
        return f"[{self.level.name}] {time_str}{source_part} | {self.message}"

    def format_detailed(self) -> str:
        """詳細フォーマット: timestamp + level + source + message + context"""
        parts = [f"[{self.timestamp.isoformat()}]", f"[{self.level.name}]"]
        if self.source:
            parts.append(f"[{self.source}]")
        parts.append(self.message)
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            parts.append(f"({context_str})")
        return " ".join(parts)
