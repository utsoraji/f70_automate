"""
アプリケーション共有ロガー

モジュールレベルの LogEventPublisher シングルトンを提供する。
ConsoleSubscriber（標準出力）はアプリ起動時に自動でサブスクライブされる。
Streamlit 向けのサブスクライバーはダッシュボード側でセッションごとに登録する。
"""

from __future__ import annotations

from f70_automate._core.logging.publisher import LogEventPublisher
from f70_automate._core.logging.console_subscriber import ConsoleSubscriber

_app_logger = LogEventPublisher()
_app_logger.subscribe(ConsoleSubscriber())


def get_app_logger() -> LogEventPublisher:
    """アプリケーション共有ロガーを返す"""
    return _app_logger
