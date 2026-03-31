from __future__ import annotations

from typing import Any, Protocol, TYPE_CHECKING

from f70_automate._core.logging.models import LogEntry, LogLevel


# =================================================================
# CONSUMER-DRIVEN PROTOCOLS
# Define what the logging logic needs.
# =================================================================


class Logger(Protocol):
    """ログを書き込む側のプロトコル（コンシューマー駆動）"""

    def debug(self, message: str, source: str | None = None, context: dict[str, Any] | None = None) -> None:
        """DEBUG レベルでログする"""
        ...

    def info(self, message: str, source: str | None = None, context: dict[str, Any] | None = None) -> None:
        """INFO レベルでログする"""
        ...

    def warning(self, message: str, source: str | None = None, context: dict[str, Any] | None = None) -> None:
        """WARNING レベルでログする"""
        ...

    def error(self, message: str, source: str | None = None, context: dict[str, Any] | None = None) -> None:
        """ERROR レベルでログする"""
        ...


class LogSubscriber(Protocol):
    """ログイベントを受け取るサブスクライバー"""

    def on_log_event(self, entry: LogEntry) -> None:
        """ログエントリを受け取る"""
        ...


class LogPublisher(Protocol):
    """ログイベント発行者"""

    def subscribe(self, subscriber: LogSubscriber, min_level: LogLevel = LogLevel.DEBUG) -> None:
        """サブスクライバーを登録"""
        ...

    def unsubscribe(self, subscriber: LogSubscriber) -> None:
        """サブスクライバーを登録解除"""
        ...

    def publish(self, entry: LogEntry) -> None:
        """ログイベントを発行"""
        ...
