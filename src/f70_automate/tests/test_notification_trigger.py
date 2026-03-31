from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import time
import unittest

from f70_automate.apps.controller.automation_usecase import (
    PeriodicNotificationRunner,
    build_periodic_message_factory,
)
from f70_automate.domains.automation.adapters.f70 import NotifyingOperationTrigger
from f70_automate.domains.f70_serial import f70_operation as f70_op
from f70_automate.domains.notification import (
    FanoutNotificationDispatcher,
    NotificationMessage,
    NotificationSettings,
    SlackBotNotifier,
    build_notification_dispatcher,
)
from f70_automate.domains.wavelogger.channel_config import ChannelConfig

@dataclass(frozen=True)
class _FakeSnapshot:
    current_physical: dict[str, float | None]


class _FakeStore:
    def __init__(self, current_physical: dict[str, float | None]) -> None:
        self._current_physical = current_physical

    def snapshot(self) -> _FakeSnapshot:
        return _FakeSnapshot(current_physical=self._current_physical)


class _FakeRuntime:
    def __init__(self, channels: tuple[ChannelConfig, ...], current_physical: dict[str, float | None]) -> None:
        self.channels = channels
        self.store = _FakeStore(current_physical)


class _FakeService:
    def __init__(self) -> None:
        self.called_operations: list[str] = []
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def is_alive(self) -> bool:
        return True

    def __call__(self, *args, **kwargs):
        _ = args
        _ = kwargs
        return None

    def call_checked(self, operation):
        self.called_operations.append(operation.name)
        return None


class _RecordingDispatcher:
    def __init__(self) -> None:
        self.messages: list[NotificationMessage] = []

    def dispatch(self, message: NotificationMessage) -> None:
        self.messages.append(message)


class _FailingDispatcher:
    def dispatch(self, message: NotificationMessage) -> None:
        _ = message
        raise RuntimeError("dispatch failed")


class TestNotifyingOperationTrigger(unittest.TestCase):
    def _build_message(self) -> NotificationMessage:
        return NotificationMessage(
            title="Triggered",
            body="automation fired",
            occurred_at=datetime.fromtimestamp(100.0),
        )

    def test_notifying_trigger_dispatches_after_operation(self):
        service = _FakeService()
        dispatcher = _RecordingDispatcher()

        trigger = NotifyingOperationTrigger(
            service=service,
            operation=f70_op.no_op,
            notification_dispatcher=dispatcher,
            notification_message_factory=lambda _: self._build_message(),
        )

        result = trigger.fire()

        self.assertEqual(result.name, "no_op")
        self.assertEqual(service.called_operations, ["no_op"])
        self.assertEqual(len(dispatcher.messages), 1)
        self.assertEqual(dispatcher.messages[0].title, "Triggered")

    def test_best_effort_policy_ignores_notification_error(self):
        service = _FakeService()
        trigger = NotifyingOperationTrigger(
            service=service,
            operation=f70_op.no_op,
            notification_dispatcher=_FailingDispatcher(),
            notification_message_factory=lambda _: self._build_message(),
            notification_failure_policy="best_effort",
        )

        result = trigger.fire()

        self.assertEqual(result.name, "no_op")
        self.assertEqual(service.called_operations, ["no_op"])

    def test_strict_policy_raises_notification_error(self):
        service = _FakeService()
        trigger = NotifyingOperationTrigger(
            service=service,
            operation=f70_op.no_op,
            notification_dispatcher=_FailingDispatcher(),
            notification_message_factory=lambda _: self._build_message(),
            notification_failure_policy="strict",
        )

        with self.assertRaisesRegex(RuntimeError, "dispatch failed"):
            trigger.fire()


class TestNotificationDispatcherBuilder(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = NotificationSettings()

    def test_dispatcher_is_none_when_notification_disabled(self):
        enabled = False

        dispatcher = build_notification_dispatcher(enabled=enabled, settings=self.settings)

        self.assertIsNone(dispatcher)

    def test_dispatcher_builds_for_slack(self):
        self.settings.slack_bot.enabled = True
        self.settings.slack_bot.channel_id = "C12345678"

        dispatcher = build_notification_dispatcher(enabled=True, settings=self.settings)

        self.assertIsInstance(dispatcher, FanoutNotificationDispatcher)
        assert isinstance(dispatcher, FanoutNotificationDispatcher)
        self.assertEqual(len(dispatcher.channels), 1)

    def test_dispatcher_can_omit_mentions(self):
        self.settings.slack_bot.enabled = True
        self.settings.slack_bot.channel_id = "C12345678"
        self.settings.slack_bot.mention_user_ids = ("U111",)

        dispatcher = build_notification_dispatcher(
            enabled=True,
            settings=self.settings,
            include_mentions=False,
        )

        self.assertIsInstance(dispatcher, FanoutNotificationDispatcher)
        assert isinstance(dispatcher, FanoutNotificationDispatcher)
        notifier = dispatcher.channels[0]
        self.assertIsInstance(notifier, SlackBotNotifier)
        assert isinstance(notifier, SlackBotNotifier)
        self.assertEqual(notifier.config.mention_user_ids, ())


class TestPeriodicNotification(unittest.TestCase):
    def test_build_periodic_message_factory_includes_all_channels(self):
        channels = (
            ChannelConfig(key="ch_pressure", label="Pressure", unit_id=1, channel_id=0, unit="Pa"),
            ChannelConfig(key="ch_temp", label="Temperature", unit_id=1, channel_id=1, unit="K"),
        )
        runtime = _FakeRuntime(
            channels,
            {"ch_pressure": 0.125, "ch_temp": None},
        )

        message = build_periodic_message_factory(runtime, "Mock")()

        self.assertEqual(message.title, "Automation Monitoring Active")
        self.assertIn("automation=ON", message.body)
        self.assertIn("Pressure: 0.125 Pa", message.body)
        self.assertIn("Temperature: N/A K", message.body)

    def test_periodic_runner_sends_immediately_and_repeats(self):
        dispatcher = _RecordingDispatcher()
        runner = PeriodicNotificationRunner(
            dispatcher=dispatcher,
            message_factory=lambda: NotificationMessage(
                title="Periodic",
                body="body",
                occurred_at=datetime.now(),
            ),
            interval_sec=0.05,
        )

        try:
            runner.start()
            time.sleep(0.02)
            self.assertGreaterEqual(len(dispatcher.messages), 1)

            deadline = time.time() + 1.0
            while len(dispatcher.messages) < 2 and time.time() < deadline:
                time.sleep(0.02)

            self.assertGreaterEqual(len(dispatcher.messages), 2)
        finally:
            runner.stop()
            runner.join(timeout=1.0)

    def test_periodic_runner_stops_when_monitor_becomes_inactive(self):
        dispatcher = _RecordingDispatcher()
        state = {"active": True}

        def _is_active() -> bool:
            return state["active"]

        def _message_factory() -> NotificationMessage:
            state["active"] = False
            return NotificationMessage(
                title="Periodic",
                body="body",
                occurred_at=datetime.now(),
            )

        runner = PeriodicNotificationRunner(
            dispatcher=dispatcher,
            message_factory=_message_factory,
            interval_sec=0.05,
            is_active=_is_active,
        )

        try:
            runner.start()
            runner.join(timeout=1.0)
            time.sleep(0.1)
            self.assertEqual(len(dispatcher.messages), 1)
        finally:
            runner.stop()
            runner.join(timeout=1.0)


if __name__ == "__main__":
    unittest.main()
