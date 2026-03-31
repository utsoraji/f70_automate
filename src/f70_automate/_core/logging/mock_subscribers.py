from __future__ import annotations

from dataclasses import dataclass, field

from f70_automate._core.logging.models import LogEntry
from f70_automate._core.logging.protocols import LogSubscriber


@dataclass
class MockLogSubscriber(LogSubscriber):
    """テスト用のモック実装: 受け取ったログエントリを蓄積"""

    entries: list[LogEntry] = field(default_factory=list, init=False)

    def on_log_event(self, entry: LogEntry) -> None:
        """ログエントリを蓄積

        Args:
            entry: ログエントリ
        """
        self.entries.append(entry)

    def clear(self) -> None:
        """蓄積したエントリをクリア"""
        self.entries.clear()

    def get_entries(self) -> list[LogEntry]:
        """蓄積したエントリを取得

        Returns:
            ログエントリのリスト
        """
        return self.entries

    def get_messages(self) -> list[str]:
        """蓄積したメッセージのみを取得

        Returns:
            メッセージのリスト
        """
        return [e.message for e in self.entries]


@dataclass
class ErrorRaisingMockSubscriber(LogSubscriber):
    """テスト用: エラーを発生させるモック（例外処理テスト用）"""

    error_to_raise: Exception

    def on_log_event(self, entry: LogEntry) -> None:
        """常にエラーを発生させる

        Args:
            entry: ログエントリ（使用されない）

        Raises:
            self.error_to_raise
        """
        raise self.error_to_raise
