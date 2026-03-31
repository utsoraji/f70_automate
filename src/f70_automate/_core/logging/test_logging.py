from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
import tempfile
from io import StringIO
import sys

from f70_automate._core.logging.models import LogEntry, LogLevel
from f70_automate._core.logging.publisher import LogEventPublisher
from f70_automate._core.logging.file_subscriber import FileLogSubscriber
from f70_automate._core.logging.console_subscriber import ConsoleSubscriber
from f70_automate._core.logging.mock_subscribers import MockLogSubscriber, ErrorRaisingMockSubscriber


class TestLogLevel(unittest.TestCase):
    """LogLevel の比較テスト"""

    def test_log_level_ordering(self) -> None:
        """ログレベルの順序"""
        self.assertTrue(LogLevel.DEBUG < LogLevel.INFO)
        self.assertTrue(LogLevel.INFO < LogLevel.WARNING)
        self.assertTrue(LogLevel.WARNING < LogLevel.ERROR)
        self.assertTrue(LogLevel.ERROR < LogLevel.CRITICAL)

    def test_log_level_lte(self) -> None:
        """ログレベルの <={演算子"""
        self.assertTrue(LogLevel.DEBUG <= LogLevel.DEBUG)
        self.assertTrue(LogLevel.DEBUG <= LogLevel.INFO)
        self.assertFalse(LogLevel.INFO <= LogLevel.DEBUG)

    def test_log_level_gt(self) -> None:
        """ログレベルの > 演算子"""
        self.assertTrue(LogLevel.CRITICAL > LogLevel.ERROR)
        self.assertFalse(LogLevel.DEBUG > LogLevel.DEBUG)


class TestLogEntry(unittest.TestCase):
    """LogEntry のフォーマットテスト"""

    def test_format_simple(self) -> None:
        """シンプルフォーマット"""
        entry = LogEntry(
            level=LogLevel.INFO,
            message="Test message",
            timestamp=datetime(2026, 3, 31, 14, 30, 45),
            source="test_module",
        )
        formatted = entry.format_simple()
        self.assertIn("[INFO]", formatted)
        self.assertIn("14:30:45", formatted)
        self.assertIn("test_module", formatted)
        self.assertIn("Test message", formatted)

    def test_format_simple_without_source(self) -> None:
        """ソースなしのシンプルフォーマット"""
        entry = LogEntry(
            level=LogLevel.DEBUG,
            message="Debug info",
            timestamp=datetime(2026, 3, 31, 10, 0, 0),
        )
        formatted = entry.format_simple()
        self.assertNotIn("(None)", formatted)
        self.assertIn("[DEBUG]", formatted)

    def test_format_detailed(self) -> None:
        """詳細フォーマット"""
        entry = LogEntry(
            level=LogLevel.ERROR,
            message="Error occurred",
            timestamp=datetime(2026, 3, 31, 14, 30, 45),
            source="error_handler",
            context={"code": 500, "module": "api"},
        )
        formatted = entry.format_detailed()
        self.assertIn("2026-03-31", formatted)
        self.assertIn("[ERROR]", formatted)
        self.assertIn("error_handler", formatted)
        self.assertIn("Error occurred", formatted)
        self.assertIn("code=500", formatted)
        self.assertIn("module=api", formatted)


class TestLogEventPublisher(unittest.TestCase):
    """LogEventPublisher のテスト"""

    def test_subscribe_and_publish(self) -> None:
        """購読と発行"""
        publisher = LogEventPublisher()
        mock_subscriber = MockLogSubscriber()

        publisher.subscribe(mock_subscriber)
        entry = LogEntry(
            level=LogLevel.INFO,
            message="Test",
            timestamp=datetime.now(),
        )
        publisher.publish(entry)

        self.assertEqual(len(mock_subscriber.entries), 1)
        self.assertEqual(mock_subscriber.entries[0].message, "Test")

    def test_unsubscribe(self) -> None:
        """購読解除"""
        publisher = LogEventPublisher()
        mock_subscriber = MockLogSubscriber()

        publisher.subscribe(mock_subscriber)
        publisher.unsubscribe(mock_subscriber)

        entry = LogEntry(
            level=LogLevel.INFO,
            message="Test",
            timestamp=datetime.now(),
        )
        publisher.publish(entry)

        self.assertEqual(len(mock_subscriber.entries), 0)

    def test_multiple_subscribers(self) -> None:
        """複数サブスクライバー"""
        publisher = LogEventPublisher()
        mock1 = MockLogSubscriber()
        mock2 = MockLogSubscriber()

        publisher.subscribe(mock1)
        publisher.subscribe(mock2)

        entry = LogEntry(
            level=LogLevel.WARNING,
            message="Alert",
            timestamp=datetime.now(),
        )
        publisher.publish(entry)

        self.assertEqual(len(mock1.entries), 1)
        self.assertEqual(len(mock2.entries), 1)

    def test_subscribe_filters_by_min_level(self) -> None:
        """subscribe 時の最小ログレベルで配信を制御する"""
        publisher = LogEventPublisher()
        info_subscriber = MockLogSubscriber()
        error_subscriber = MockLogSubscriber()

        publisher.subscribe(info_subscriber, min_level=LogLevel.INFO)
        publisher.subscribe(error_subscriber, min_level=LogLevel.ERROR)

        publisher.debug("debug msg")
        publisher.info("info msg")
        publisher.error("error msg")

        self.assertEqual([entry.level for entry in info_subscriber.entries], [LogLevel.INFO, LogLevel.ERROR])
        self.assertEqual([entry.level for entry in error_subscriber.entries], [LogLevel.ERROR])

    def test_subscriber_error_does_not_break_publishing(self) -> None:
        """サブスクライバーのエラーが他に影響しない"""
        publisher = LogEventPublisher()
        error_sub = ErrorRaisingMockSubscriber(error_to_raise=RuntimeError("Test error"))
        mock_sub = MockLogSubscriber()

        publisher.subscribe(error_sub)
        publisher.subscribe(mock_sub)

        entry = LogEntry(
            level=LogLevel.INFO,
            message="Should be received by mock_sub",
            timestamp=datetime.now(),
        )
        publisher.publish(entry)

        # error_sub がエラーを発生させても、mock_sub はメッセージを受け取る
        self.assertEqual(len(mock_sub.entries), 1)

    def test_convenience_methods(self) -> None:
        """便利メソッド (debug, info, warning, error, critical)"""
        publisher = LogEventPublisher()
        mock_sub = MockLogSubscriber()
        publisher.subscribe(mock_sub)

        publisher.debug("debug msg", source="test")
        publisher.info("info msg")
        publisher.warning("warning msg", context={"key": "value"})
        publisher.error("error msg")
        publisher.critical("critical msg")

        self.assertEqual(len(mock_sub.entries), 5)
        self.assertEqual(mock_sub.entries[0].level, LogLevel.DEBUG)
        self.assertEqual(mock_sub.entries[1].level, LogLevel.INFO)
        self.assertEqual(mock_sub.entries[2].level, LogLevel.WARNING)
        self.assertEqual(mock_sub.entries[3].level, LogLevel.ERROR)
        self.assertEqual(mock_sub.entries[4].level, LogLevel.CRITICAL)


class TestFileLogSubscriber(unittest.TestCase):
    """FileLogSubscriber のテスト"""

    def test_write_to_file(self) -> None:
        """ファイルへの書き込み"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            subscriber = FileLogSubscriber(log_file, detailed=False)

            entry = LogEntry(
                level=LogLevel.INFO,
                message="Test log",
                timestamp=datetime(2026, 3, 31, 14, 30, 45),
                source="test",
            )
            subscriber.on_log_event(entry)

            # ファイルが作成されたか確認
            self.assertTrue(log_file.exists())

            # ファイル内容を確認
            content = log_file.read_text(encoding="utf-8")
            self.assertIn("[INFO]", content)
            self.assertIn("14:30:45", content)
            self.assertIn("Test log", content)

    def test_create_parent_directories(self) -> None:
        """親ディレクトリが存在しない場合の作成"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "subdir1" / "subdir2" / "test.log"
            subscriber = FileLogSubscriber(log_file)

            entry = LogEntry(
                level=LogLevel.INFO,
                message="Test",
                timestamp=datetime.now(),
            )
            subscriber.on_log_event(entry)

            self.assertTrue(log_file.exists())

    def test_append_mode(self) -> None:
        """複数回の追記"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            subscriber = FileLogSubscriber(log_file)

            # 最初のエントリ
            entry1 = LogEntry(
                level=LogLevel.INFO,
                message="First",
                timestamp=datetime.now(),
            )
            subscriber.on_log_event(entry1)

            # 2番目のエントリ
            entry2 = LogEntry(
                level=LogLevel.WARNING,
                message="Second",
                timestamp=datetime.now(),
            )
            subscriber.on_log_event(entry2)

            content = log_file.read_text(encoding="utf-8")
            lines = content.strip().split("\n")
            self.assertEqual(len(lines), 2)

    def test_detailed_format(self) -> None:
        """詳細フォーマット"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            subscriber = FileLogSubscriber(log_file, detailed=True)

            entry = LogEntry(
                level=LogLevel.ERROR,
                message="Detailed log",
                timestamp=datetime(2026, 3, 31, 14, 30, 45),
                source="module",
                context={"code": 500},
            )
            subscriber.on_log_event(entry)

            content = log_file.read_text(encoding="utf-8")
            self.assertIn("2026-03-31", content)
            self.assertIn("[ERROR]", content)
            self.assertIn("module", content)
            self.assertIn("code=500", content)


class TestConsoleSubscriber(unittest.TestCase):
    """ConsoleSubscriber のテスト"""

    def test_write_to_stdout(self) -> None:
        """標準出力への書き込み"""
        captured_output = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_output

        try:
            subscriber = ConsoleSubscriber(detailed=False, flush=True)

            entry = LogEntry(
                level=LogLevel.INFO,
                message="Console test",
                timestamp=datetime(2026, 3, 31, 14, 30, 45),
                source="test",
            )
            subscriber.on_log_event(entry)

            output = captured_output.getvalue()
            self.assertIn("[INFO]", output)
            self.assertIn("14:30:45", output)
            self.assertIn("Console test", output)
        finally:
            sys.stdout = old_stdout

    def test_detailed_format_to_stdout(self) -> None:
        """詳細フォーマットで標準出力へ出力"""
        captured_output = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_output

        try:
            subscriber = ConsoleSubscriber(detailed=True)

            entry = LogEntry(
                level=LogLevel.ERROR,
                message="Detailed console",
                timestamp=datetime(2026, 3, 31, 14, 30, 45),
                source="module",
                context={"code": 500},
            )
            subscriber.on_log_event(entry)

            output = captured_output.getvalue()
            self.assertIn("2026-03-31", output)
            self.assertIn("[ERROR]", output)
            self.assertIn("module", output)
            self.assertIn("code=500", output)
        finally:
            sys.stdout = old_stdout


if __name__ == "__main__":
    unittest.main()
