from __future__ import annotations

import sys
from dataclasses import dataclass

from f70_automate._core.logging.models import LogEntry
from f70_automate._core.logging.protocols import LogSubscriber


@dataclass
class ConsoleSubscriber(LogSubscriber):
    """標準出力にログを出力するサブスクライバー"""

    detailed: bool = False
    flush: bool = True

    def on_log_event(self, entry: LogEntry) -> None:
        """ログエントリを標準出力に出力

        Args:
            entry: ログエントリ
        """
        formatted = entry.format_detailed() if self.detailed else entry.format_simple()
        print(formatted, file=sys.stdout, flush=self.flush)
