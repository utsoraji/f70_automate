from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, Protocol, TypeVar

from f70_automate._core.threading import ThreadRunner

# Monitoring engine core.
# Responsibility:
# - consume value events from an EventStream
# - evaluate a Condition against a bounded sample window
# - invoke a Trigger when the condition matches
# - expose monitoring session state through MonitorSnapshot
#
# Non-responsibility:
# - stream/source availability policy
# - UI wording and orchestration policy
# - concrete source / trigger integrations
# - concrete condition catalogs

TValue = TypeVar("TValue")
TTriggerResult = TypeVar("TTriggerResult", covariant=True)


@dataclass(frozen=True)
class ValueEvent(Generic[TValue]):
    value: TValue | None
    occurred_at: datetime


class EventStream(Protocol[TValue]):
    def get(self) -> ValueEvent[TValue] | None: ...

    def close(self) -> None: ...


class Trigger(Protocol[TTriggerResult]):
    def fire(self) -> TTriggerResult: ...


@dataclass(frozen=True)
class SampleWindow(Generic[TValue]):
    values: tuple[TValue, ...]


class Condition(Protocol[TValue]):
    @property
    def window_size(self) -> int: ...

    def should_trigger(
        self,
        window: SampleWindow[TValue],
        occurred_at: datetime,
        last_trigger_time: datetime | None,
    ) -> bool: ...


@dataclass(frozen=True)
class MonitorSnapshot(Generic[TTriggerResult]):
    is_running: bool
    last_trigger_time: datetime | None = None
    last_error: Exception | None = None
    last_error_time: datetime | None = None
    trigger_count: int = 0
    last_trigger_result: TTriggerResult | None = None


@dataclass
class _MonitorState(Generic[TTriggerResult]):
    last_trigger_time: datetime | None = None
    last_error: Exception | None = None
    last_error_time: datetime | None = None
    trigger_count: int = 0
    last_trigger_result: TTriggerResult | None = None
    stop_requested: bool = False

    def snapshot(self, *, is_running: bool) -> MonitorSnapshot[TTriggerResult]:
        return MonitorSnapshot(
            is_running=is_running,
            last_trigger_time=self.last_trigger_time,
            last_error=self.last_error,
            last_error_time=self.last_error_time,
            trigger_count=self.trigger_count,
            last_trigger_result=self.last_trigger_result,
        )


@dataclass(frozen=True)
class MonitorSpec(Generic[TValue, TTriggerResult]):
    condition: Condition[TValue]
    trigger: Trigger[TTriggerResult]
    max_trigger_count: int | None = None


class MonitorSession(Generic[TValue, TTriggerResult]):
    # Monitoring domain session.
    # It consumes one event at a time, updates session state, and decides
    # whether monitoring should stop. It does not own background execution.
    def __init__(self, spec: MonitorSpec[TValue, TTriggerResult]):
        self._spec = spec
        self._state: _MonitorState[TTriggerResult] = _MonitorState()
        self._window: deque[TValue] = deque(maxlen=self._spec.condition.window_size)
        self._lock = threading.Lock()

    def consume(self, event: ValueEvent[TValue]) -> bool:
        value = event.value
        if value is None:
            return not self.is_stop_requested()

        result: TTriggerResult | None = None
        triggered = False
        occurred_at = event.occurred_at

        with self._lock:
            if self._state.stop_requested:
                return False
            self._window.append(value)
            window = SampleWindow(values=tuple(self._window))
            last_trigger_time = self._state.last_trigger_time

        if not self._spec.condition.should_trigger(window, occurred_at, last_trigger_time):
            return True

        try:
            result = self._spec.trigger.fire()
            triggered = True
        except Exception as exc:
            with self._lock:
                self._state.last_error = exc
                self._state.last_error_time = datetime.now()
                self._state.stop_requested = True
            return False

        if triggered:
            with self._lock:
                self._state.last_trigger_time = occurred_at
                self._state.trigger_count += 1
                self._state.last_trigger_result = result
                self._state.last_error = None
                self._state.last_error_time = None
                if (
                    self._spec.max_trigger_count is not None
                    and self._state.trigger_count >= self._spec.max_trigger_count
                ):
                    self._state.stop_requested = True
                    return False
        return True

    def request_stop(self) -> None:
        with self._lock:
            self._state.stop_requested = True

    def is_stop_requested(self) -> bool:
        with self._lock:
            return self._state.stop_requested

    def snapshot(self, *, is_running: bool = False) -> MonitorSnapshot[TTriggerResult]:
        with self._lock:
            return self._state.snapshot(is_running=is_running)


class ThreadedMonitorRunner(Generic[TValue, TTriggerResult], ThreadRunner):
    # Single-use background runner.
    # It owns EventStream consumption and delegates event processing to the
    # MonitorSession. Create a new runner for each monitoring run.
    def __init__(
        self,
        stream: EventStream[TValue],
        session: MonitorSession[TValue, TTriggerResult],
    ):
        super().__init__()
        self._stream = stream
        self._session = session

    def start(self) -> None:
        """Start the monitor runner."""
        super().start()

    def stop(self) -> None:
        """Request the monitor runner to stop and clean up resources."""
        super().stop()
        self._session.request_stop()
        self._stream.close()

    def is_running(self) -> bool:
        """Check if the monitor runner is currently active."""
        return self.is_alive() and not self.is_stop_requested()

    def snapshot(self) -> MonitorSnapshot[TTriggerResult]:
        """Get a snapshot of the current monitoring state."""
        return self._session.snapshot(is_running=self.is_running())

    def _run_loop(self) -> None:
        """Run the monitoring loop until stop is requested."""
        try:
            while self.is_running():
                event = self._stream.get()
                if event is None:
                    break
                if not self._session.consume(event):
                    break
        finally:
            self._stream.close()
