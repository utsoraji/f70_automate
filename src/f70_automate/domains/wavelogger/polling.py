from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from f70_automate._core.threading import ThreadRunner
from f70_automate.domains.wavelogger import winapp_wrapper
from f70_automate.domains.wavelogger.channel_config import ChannelConfig

from f70_automate.domains.wavelogger.protocols import *
from f70_automate.domains.wavelogger.models import *

DEFAULT_CHANNEL = ChannelConfig(
    key="default",
    label="Channel 0",
    unit_id=1,
    channel_id=0,
)



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
                try:
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
                finally:
                    app.measurement.stop()
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
            app_factory=app_factory or (lambda: winapp_wrapper.WaveLoggerApp(visible=True)),
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
