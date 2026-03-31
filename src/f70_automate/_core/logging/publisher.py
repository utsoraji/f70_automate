from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime

from f70_automate._core.logging.models import LogEntry, LogLevel
from f70_automate._core.logging.protocols import LogPublisher, LogSubscriber


@dataclass(frozen=True)
class _SubscriberRegistration:
    subscriber: LogSubscriber
    min_level: LogLevel = LogLevel.DEBUG


@dataclass
class LogEventPublisher(LogPublisher):
    """Publisher-Subscriber パターンを使用したログイベント発行者"""

    _subscribers: list[_SubscriberRegistration] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def subscribe(self, subscriber: LogSubscriber, min_level: LogLevel = LogLevel.DEBUG) -> None:
        """サブスクライバーを登録

        Args:
            subscriber: 登録するサブスクライバー
            min_level: このレベル以上のログのみ配信する閾値
        """
        with self._lock:
            if any(r.subscriber is subscriber for r in self._subscribers):
                return
            self._subscribers.append(_SubscriberRegistration(subscriber=subscriber, min_level=min_level))

    def unsubscribe(self, subscriber: LogSubscriber) -> None:
        """サブスクライバーを登録解除

        Args:
            subscriber: 登録解除するサブスクライバー
        """
        with self._lock:
            self._subscribers = [registration for registration in self._subscribers if registration.subscriber != subscriber]

    def publish(self, entry: LogEntry) -> None:
        """ログイベントを発行。スレッドセーフ。

        Args:
            entry: 発行するログエントリ
        """
        with self._lock:
            subscribers = list(self._subscribers)

        for registration in subscribers:
            if entry.level < registration.min_level:
                continue

            try:
                registration.subscriber.on_log_event(entry)
            except Exception:
                # サブスクライバーのエラーが他に影響しないように
                pass

    def log(self, level: LogLevel, message: str, source: str | None = None, context: dict | None = None) -> None:
        """便利メソッド: ログエントリを作成して発行

        Args:
            level: ログレベル
            message: ログメッセージ
            source: ログソース（例: モジュール名)
            context: 追加コンテキスト情報
        """
        entry = LogEntry(level=level, message=message, timestamp=datetime.now(), source=source, context=context)
        self.publish(entry)

    def debug(self, message: str, source: str | None = None, context: dict | None = None) -> None:
        """DEBUG レベルでログする"""
        self.log(LogLevel.DEBUG, message, source, context)

    def info(self, message: str, source: str | None = None, context: dict | None = None) -> None:
        """INFO レベルでログする"""
        self.log(LogLevel.INFO, message, source, context)

    def warning(self, message: str, source: str | None = None, context: dict | None = None) -> None:
        """WARNING レベルでログする"""
        self.log(LogLevel.WARNING, message, source, context)

    def error(self, message: str, source: str | None = None, context: dict | None = None) -> None:
        """ERROR レベルでログする"""
        self.log(LogLevel.ERROR, message, source, context)

    def critical(self, message: str, source: str | None = None, context: dict | None = None) -> None:
        """CRITICAL レベルでログする"""
        self.log(LogLevel.CRITICAL, message, source, context)
