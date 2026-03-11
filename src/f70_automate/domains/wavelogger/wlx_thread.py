from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from f70_automate._core.threading import ThreadRunner
from f70_automate.domains.wavelogger import wlx_wrapper
from f70_automate.domains.wavelogger.channel_config import ChannelConfig


DEFAULT_CHANNEL = ChannelConfig(
    key="default",
    label="Channel 0",
    unit_id=1,
    channel_id=0,
)


class WaveLoggerDocumentLike(Protocol):
    @property
    def data_count(self) -> int: ...

    def get_data(self, unit_id: int, channel_id: int, pos: int) -> float | None: ...

    def get_current_data(self, unit_id: int, channel_id: int) -> float | None: ...


class WaveLoggerConnectorLike(Protocol):
    def setup_usb(self, device_id: int) -> None: ...


class WaveLoggerMeasurementLike(Protocol):
    def load_settings(self, path: Path | str) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


class WaveLoggerAppLike(Protocol):
    @property
    def connector(self) -> WaveLoggerConnectorLike: ...

    @property
    def measurement(self) -> WaveLoggerMeasurementLike: ...

    def get_active_document(self) -> WaveLoggerDocumentLike: ...

    def __enter__(self) -> "WaveLoggerAppLike": ...

    def __exit__(self, exc_type, exc_val, exc_tb) -> None: ...


@dataclass(frozen=True)
class PhysicalSampleBatch:
    received_at: float
    physical_values: tuple[tuple[ChannelConfig, float | None], ...]


SampleListener = Callable[[PhysicalSampleBatch], None]


@dataclass(frozen=True)
class WLXStoreSnapshot:
    current_voltage: dict[str, float | None]
    current_physical: dict[str, float | None]
    sample_count: int
    exception: Exception | None


@dataclass(frozen=True)
class WLXChannelSamples:
    channel: ChannelConfig
    current_voltage: float | None
    current_physical: float | None
    voltage_history: tuple[float | None, ...]
    physical_history: tuple[float | None, ...]

    @property
    def sample_count(self) -> int:
        return len(self.voltage_history)


@dataclass(frozen=True)
class WLXCollectedSamples:
    channels: tuple[WLXChannelSamples, ...]

    def sample_count(self) -> int:
        expected_sample_count: int | None = None
        for channel_samples in self.channels:
            if channel_samples.sample_count != len(channel_samples.physical_history):
                raise ValueError(
                    f"Mismatched sample lengths for channel '{channel_samples.channel.key}'."
                )
            if expected_sample_count is None:
                expected_sample_count = channel_samples.sample_count
                continue
            if channel_samples.sample_count != expected_sample_count:
                raise ValueError("All channels must append the same number of samples.")
        return expected_sample_count or 0

    def current_voltage_by_key(self) -> dict[str, float | None]:
        return {
            channel_samples.channel.key: channel_samples.current_voltage
            for channel_samples in self.channels
        }

    def current_physical_by_key(self) -> dict[str, float | None]:
        return {
            channel_samples.channel.key: channel_samples.current_physical
            for channel_samples in self.channels
        }

    def physical_values_at(
        self, offset: int
    ) -> tuple[tuple[ChannelConfig, float | None], ...]:
        return tuple(
            (channel_samples.channel, channel_samples.physical_history[offset])
            for channel_samples in self.channels
        )


@dataclass
class _WLXChannelState:
    current_voltage: float | None = None
    current_physical: float | None = None
    voltage_history: list[float | None] = field(default_factory=list)
    physical_history: list[float | None] = field(default_factory=list)


class WLXSampleStore:
    def __init__(self, channels: tuple[ChannelConfig, ...]):
        if not channels:
            raise ValueError("At least one channel must be configured.")
        self._channels = channels
        self._default_channel = channels[0]
        self._lock = threading.Lock()
        self._channel_state = {channel.key: _WLXChannelState() for channel in channels}
        self._exception: Exception | None = None

    @property
    def default_channel(self) -> ChannelConfig:
        return self._default_channel

    @property
    def exception(self) -> Exception | None:
        with self._lock:
            return self._exception

    def set_exception(self, exc: Exception) -> None:
        with self._lock:
            self._exception = exc

    def clear_exception(self) -> None:
        with self._lock:
            self._exception = None

    def check_exception(self) -> None:
        with self._lock:
            if self._exception is not None:
                raise self._exception

    def snapshot(self) -> WLXStoreSnapshot:
        with self._lock:
            return WLXStoreSnapshot(
                current_voltage={
                    channel.key: self._channel_state[channel.key].current_voltage
                    for channel in self._channels
                },
                current_physical={
                    channel.key: self._channel_state[channel.key].current_physical
                    for channel in self._channels
                },
                sample_count=len(self._channel_state[self._default_channel.key].voltage_history),
                exception=self._exception,
            )

    def current_physical_values(self) -> dict[str, float | None]:
        self.check_exception()
        with self._lock:
            return {
                channel.key: self._channel_state[channel.key].current_physical
                for channel in self._channels
            }

    def get_current_voltage(self, channel: ChannelConfig) -> float | None:
        self.check_exception()
        with self._lock:
            return self._channel_state[channel.key].current_voltage

    def get_current_physical(self, channel: ChannelConfig) -> float | None:
        self.check_exception()
        with self._lock:
            return self._channel_state[channel.key].current_physical

    def get_voltage_history(self, channel: ChannelConfig) -> list[float | None]:
        self.check_exception()
        with self._lock:
            return self._channel_state[channel.key].voltage_history.copy()

    def get_physical_history(self, channel: ChannelConfig) -> list[float | None]:
        self.check_exception()
        with self._lock:
            return self._channel_state[channel.key].physical_history.copy()

    def get_local_data_count(self) -> int:
        with self._lock:
            return len(self._channel_state[self._default_channel.key].voltage_history)

    def append_samples(
        self,
        *,
        samples: WLXCollectedSamples,
    ) -> None:
        samples.sample_count()
        with self._lock:
            for channel_samples in samples.channels:
                state = self._channel_state[channel_samples.channel.key]
                state.current_voltage = channel_samples.current_voltage
                state.current_physical = channel_samples.current_physical
                state.voltage_history.extend(channel_samples.voltage_history)
                state.physical_history.extend(channel_samples.physical_history)


class WLXPhysicalPublisher:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._physical_listeners: list[SampleListener] = []

    def add_physical_listener(self, listener: SampleListener) -> None:
        with self._lock:
            self._physical_listeners.append(listener)

    def remove_physical_listener(self, listener: SampleListener) -> None:
        with self._lock:
            self._physical_listeners = [
                existing for existing in self._physical_listeners if existing != listener
            ]

    def emit_samples(
        self,
        batch: PhysicalSampleBatch,
    ) -> None:
        with self._lock:
            listeners = tuple(self._physical_listeners)
        for listener in listeners:
            listener(batch)


class WLXPollingSession:
    def __init__(
        self,
        *,
        filepath: Path | str,
        app_factory: Callable[[], WaveLoggerAppLike],
        poll_interval: float,
        channels: tuple[ChannelConfig, ...],
        store: WLXSampleStore,
        publisher: WLXPhysicalPublisher,
    ):
        self._filepath = filepath
        self._app_factory = app_factory
        self._poll_interval = poll_interval
        self._channels = channels
        self._store = store
        self._publisher = publisher

    def _read_channel_samples(
        self,
        *,
        doc: WaveLoggerDocumentLike,
        local_data_count: int,
        data_count: int,
    ) -> WLXCollectedSamples:
        channel_samples_list: list[WLXChannelSamples] = []
        for channel in self._channels:
            voltage = doc.get_current_data(channel.unit_id, channel.channel_id)
            channel_voltage_data = [
                doc.get_data(channel.unit_id, channel.channel_id, i)
                for i in range(local_data_count, data_count)
            ]
            channel_samples_list.append(
                WLXChannelSamples(
                    channel=channel,
                    current_voltage=voltage,
                    current_physical=channel.voltage_to_physical(voltage),
                    voltage_history=tuple(channel_voltage_data),
                    physical_history=tuple(
                        channel.voltage_to_physical(value) for value in channel_voltage_data
                    ),
                )
            )

        return WLXCollectedSamples(
            channels=tuple(channel_samples_list),
        )

    def _emit_batches(
        self,
        *,
        samples: WLXCollectedSamples,
        received_at: float,
    ) -> None:
        emitted_sample_count = samples.sample_count()
        for offset in range(emitted_sample_count):
            batch = PhysicalSampleBatch(
                received_at=received_at,
                physical_values=samples.physical_values_at(offset),
            )
            self._publisher.emit_samples(batch)

    def run(self, stop_requested: Callable[[], bool]) -> None:
        try:
            with self._app_factory() as app:
                app.connector.setup_usb(device_id=0)
                app.measurement.load_settings(self._filepath)
                app.measurement.start()
                doc = app.get_active_document()

                while not stop_requested():
                    data_count = doc.data_count
                    local_data_count = self._store.get_local_data_count()
                    batch_received_at = time.time()
                    samples = self._read_channel_samples(
                        doc=doc,
                        local_data_count=local_data_count,
                        data_count=data_count,
                    )
                    self._store.append_samples(samples=samples)
                    self._emit_batches(samples=samples, received_at=batch_received_at)
                    time.sleep(self._poll_interval)
        except Exception as exc:
            self._store.set_exception(exc)


class ThreadedPollingRunner(ThreadRunner):
    """Background runner for WaveLogger polling."""

    def __init__(self, session: WLXPollingSession):
        super().__init__()
        self._session = session

    def _run_loop(self) -> None:
        """Run the polling loop until stop is requested."""
        self._session.run(stop_requested=self.is_stop_requested)


class WLXRuntime:
    def __init__(
        self,
        *,
        channels: tuple[ChannelConfig, ...],
        store: WLXSampleStore,
        publisher: WLXPhysicalPublisher,
        session: WLXPollingSession,
        runner: ThreadedPollingRunner,
    ) -> None:
        self._channels = channels
        self._store = store
        self._publisher = publisher
        self._session = session
        self._runner = runner

    @property
    def channels(self) -> tuple[ChannelConfig, ...]:
        return self._channels

    @property
    def store(self) -> WLXSampleStore:
        return self._store

    @property
    def publisher(self) -> WLXPhysicalPublisher:
        return self._publisher

    @property
    def runner(self) -> ThreadedPollingRunner:
        return self._runner

    @classmethod
    def create(
        cls,
        *,
        filepath: Path | str,
        app_factory: Callable[[], WaveLoggerAppLike] | None = None,
        poll_interval: float = 1.0,
        channels: tuple[ChannelConfig, ...] | None = None,
    ) -> "WLXRuntime":
        resolved_channels = channels or (DEFAULT_CHANNEL,)
        store = WLXSampleStore(resolved_channels)
        publisher = WLXPhysicalPublisher()
        session = WLXPollingSession(
            filepath=filepath,
            app_factory=app_factory or (lambda: wlx_wrapper.WaveLoggerApp(visible=True)),
            poll_interval=poll_interval,
            channels=resolved_channels,
            store=store,
            publisher=publisher,
        )
        runner = ThreadedPollingRunner(session)
        return cls(
            channels=resolved_channels,
            store=store,
            publisher=publisher,
            session=session,
            runner=runner,
        )
