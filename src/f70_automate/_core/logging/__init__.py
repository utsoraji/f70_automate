"""
_core.logging: Publisher-Subscriber パターンを使用したローカルログ機構

ログの発行・購読・保存を統合的に管理します。
"""

from f70_automate._core.logging.models import LogEntry, LogLevel
from f70_automate._core.logging.protocols import Logger, LogPublisher, LogSubscriber
from f70_automate._core.logging.publisher import LogEventPublisher
from f70_automate._core.logging.file_subscriber import FileLogSubscriber
from f70_automate._core.logging.console_subscriber import ConsoleSubscriber
from f70_automate._core.logging.mock_subscribers import MockLogSubscriber, ErrorRaisingMockSubscriber
from f70_automate._core.logging.app_logger import get_app_logger

__all__ = [
    "LogEntry",
    "LogLevel",
    "Logger",
    "LogPublisher",
    "LogSubscriber",
    "LogEventPublisher",
    "FileLogSubscriber",
    "ConsoleSubscriber",
    "MockLogSubscriber",
    "ErrorRaisingMockSubscriber",
    "get_app_logger",
]
