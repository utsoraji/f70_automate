"""Tests for apps/dashboards logging subscribers."""

from __future__ import annotations

import unittest
from datetime import datetime

from f70_automate._core.logging.models import LogEntry, LogLevel
from f70_automate.apps.dashboards.logging_subscribers import StreamlitConsoleSubscriber


class TestStreamlitConsoleSubscriber(unittest.TestCase):
    """StreamlitConsoleSubscriber のテスト"""

    def setUp(self) -> None:
        StreamlitConsoleSubscriber._reset_singleton()

    def tearDown(self) -> None:
        StreamlitConsoleSubscriber._reset_singleton()

    def test_buffer_accumulation(self) -> None:
        """バッファへの蓄積"""
        subscriber = StreamlitConsoleSubscriber()

        for i in range(5):
            entry = LogEntry(
                level=LogLevel.INFO,
                message=f"Message {i}",
                timestamp=datetime.now(),
            )
            subscriber.on_log_event(entry)

        self.assertEqual(len(subscriber.get_buffer()), 5)

    def test_buffer_max_lines(self) -> None:
        """バッファの最大行数制限"""
        subscriber = StreamlitConsoleSubscriber(max_lines=3)

        for i in range(5):
            entry = LogEntry(
                level=LogLevel.INFO,
                message=f"Message {i}",
                timestamp=datetime.now(),
            )
            subscriber.on_log_event(entry)

        # 最後の3つのエントリのみ保持
        self.assertEqual(len(subscriber.get_buffer()), 3)
        messages = subscriber.get_messages()

        buffer_str = subscriber.get_buffer_str()
        self.assertIn("Message 2", buffer_str)
        self.assertIn("Message 3", buffer_str)
        self.assertIn("Message 4", buffer_str)
        self.assertNotIn("Message 0", buffer_str)
        self.assertNotIn("Message 1", buffer_str)

    def test_clear_buffer(self) -> None:
        """バッファクリア"""
        subscriber = StreamlitConsoleSubscriber()

        entry = LogEntry(
            level=LogLevel.INFO,
            message="Test",
            timestamp=datetime.now(),
        )
        subscriber.on_log_event(entry)

        self.assertEqual(len(subscriber.get_buffer()), 1)
        subscriber.clear_buffer()
        self.assertEqual(len(subscriber.get_buffer()), 0)

    def test_formatted_output(self) -> None:
        """シンプルフォーマット出力"""
        subscriber = StreamlitConsoleSubscriber(detailed=False)

        entry = LogEntry(
            level=LogLevel.WARNING,
            message="Warning message",
            timestamp=datetime(2026, 3, 31, 15, 45, 30),
            source="test_module",
        )
        subscriber.on_log_event(entry)

        buffer_str = subscriber.get_buffer_str()
        self.assertIn("[WARNING]", buffer_str)
        self.assertIn("15:45:30", buffer_str)
        self.assertIn("Warning message", buffer_str)

    def test_detailed_format(self) -> None:
        """詳細フォーマット出力"""
        subscriber = StreamlitConsoleSubscriber(detailed=True)

        entry = LogEntry(
            level=LogLevel.ERROR,
            message="Error message",
            timestamp=datetime(2026, 3, 31, 15, 45, 30),
            source="error_module",
            context={"errno": 500},
        )
        subscriber.on_log_event(entry)

        buffer_str = subscriber.get_buffer_str()
        self.assertIn("2026-03-31", buffer_str)
        self.assertIn("[ERROR]", buffer_str)
        self.assertIn("error_module", buffer_str)
        self.assertIn("errno=500", buffer_str)


if __name__ == "__main__":
    unittest.main()
