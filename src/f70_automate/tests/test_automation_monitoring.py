import time
import unittest
from datetime import datetime
import queue

from f70_automate.domains.automation.conditions import ThresholdBelowCondition
from f70_automate.domains.automation.monitoring import (
    EventStream,
    MonitorSession,
    MonitorSpec,
    ThreadedMonitorRunner,
    ValueEvent,
)
from f70_automate.domains.automation.settings import (
    AutomationSettings,
    default_thresholds_by_channel,
)
from f70_automate.domains.wavelogger.channel_config import ChannelConfig


class FakeTrigger:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def fire(self) -> int:
        self.calls.append(1)
        return 1


class FakeEventStream(EventStream[float]):
    def __init__(self) -> None:
        self.events: queue.SimpleQueue[ValueEvent[float] | None] = queue.SimpleQueue()

    def get(self) -> ValueEvent[float] | None:
        return self.events.get()

    def close(self) -> None:
        self.events.put(None)

    def push(self, event: ValueEvent[float]) -> None:
        self.events.put(event)


class TestAutomationMonitoring(unittest.TestCase):
    def setUp(self) -> None:
        self.pressure = ChannelConfig("pressure", "Pressure", 1, 0, unit="Pa")
        self.temperature = ChannelConfig("temperature", "Temperature", 1, 1, unit="K")
        self.channels = (self.pressure, self.temperature)

    def test_settings_manage_thresholds_per_channel(self):
        settings = AutomationSettings(channels=self.channels)

        settings.threshold = 1.2
        settings.selected_channel_key = self.temperature.key
        settings.threshold = 280.0

        self.assertEqual(settings.selected_channel, self.temperature)
        self.assertEqual(settings.threshold, 280.0)
        self.assertEqual(settings.thresholds_by_channel_key[self.pressure.key], 1.2)

    def test_default_thresholds_cover_all_channels(self):
        thresholds = default_thresholds_by_channel(self.channels, default_threshold=0.5)

        self.assertEqual(thresholds, {"pressure": 0.5, "temperature": 0.5})

    def test_monitoring_triggers_after_required_consecutive_samples(self):
        stream = FakeEventStream()
        trigger = FakeTrigger()
        spec = MonitorSpec(
            condition=ThresholdBelowCondition(
                threshold=0.5,
                cooldown_sec=0.0,
                required_sample_count=3,
            ),
            trigger=trigger,
            max_trigger_count=1,
        )

        session = MonitorSession(spec=spec)
        monitor = ThreadedMonitorRunner(stream=stream, session=session)
        monitor.start()
        stream.push(ValueEvent(value=0.8, occurred_at=datetime.fromtimestamp(100.0)))
        stream.push(ValueEvent(value=0.4, occurred_at=datetime.fromtimestamp(101.0)))
        stream.push(ValueEvent(value=0.3, occurred_at=datetime.fromtimestamp(102.0)))
        time.sleep(0.05)
        self.assertEqual(trigger.calls, [])
        stream.push(ValueEvent(value=0.2, occurred_at=datetime.fromtimestamp(103.0)))

        deadline = time.time() + 0.5
        while time.time() < deadline and not trigger.calls:
            time.sleep(0.01)
        stream.push(ValueEvent(value=0.1, occurred_at=datetime.fromtimestamp(104.0)))
        time.sleep(0.05)
        snapshot = monitor.snapshot()
        monitor.stop()

        self.assertEqual(trigger.calls, [1])
        self.assertEqual(snapshot.last_trigger_result, 1)
        self.assertEqual(snapshot.trigger_count, 1)
        self.assertEqual(snapshot.last_trigger_time, datetime.fromtimestamp(103.0))
        self.assertFalse(snapshot.is_running)

    def test_monitoring_records_trigger_error(self):
        class FailingTrigger:
            def fire(self) -> int:
                raise RuntimeError("trigger failed")

        stream = FakeEventStream()
        spec = MonitorSpec(
            condition=ThresholdBelowCondition(threshold=0.5),
            trigger=FailingTrigger(),
        )

        session = MonitorSession(spec=spec)
        monitor = ThreadedMonitorRunner(stream=stream, session=session)
        monitor.start()
        stream.push(ValueEvent(value=0.1, occurred_at=datetime.fromtimestamp(100.0)))

        deadline = time.time() + 0.5
        while time.time() < deadline and monitor.is_running():
            time.sleep(0.01)
        snapshot = monitor.snapshot()

        self.assertFalse(snapshot.is_running)
        self.assertIsInstance(snapshot.last_error, RuntimeError)
        self.assertEqual(str(snapshot.last_error), "trigger failed")
        self.assertIsNotNone(snapshot.last_error_time)

    def test_monitor_runner_cannot_restart_after_stop(self):
        stream = FakeEventStream()
        trigger = FakeTrigger()
        spec = MonitorSpec(
            condition=ThresholdBelowCondition(threshold=0.5),
            trigger=trigger,
        )

        session = MonitorSession(spec=spec)
        monitor = ThreadedMonitorRunner(stream=stream, session=session)
        monitor.start()
        monitor.stop()

        with self.assertRaisesRegex(RuntimeError, "cannot be started more than once"):
            monitor.start()


if __name__ == "__main__":
    unittest.main()
