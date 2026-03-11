from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import random
import time


@dataclass
class FakeWaveLoggerDocument:
    samples_by_channel: dict[tuple[int, int], list[float | None]]
    fail_on_current_call: int | None = None
    sample_interval_sec: float = 1.0
    random_step: float = 0.02
    _current_calls: int = 0
    _channel_count: int = field(init=False, repr=False)
    _started_at: float = field(default_factory=time.monotonic, init=False, repr=False)
    _rng: random.Random = field(default_factory=random.Random, init=False, repr=False)

    def __post_init__(self) -> None:
        self._channel_count = max(1, len(self.samples_by_channel))

    @property
    def data_count(self) -> int:
        if self.sample_interval_sec <= 0:
            first_channel = next(iter(self.samples_by_channel.values()))
            return len(first_channel)
        elapsed = time.monotonic() - self._started_at
        return max(1, int(elapsed / self.sample_interval_sec) + 1)

    def get_data(self, unit_id: int, channel_id: int, pos: int) -> float | None:
        samples = self.samples_by_channel[(unit_id, channel_id)]
        self._extend_samples_to_index(samples, pos)
        return samples[pos]

    def get_current_data(self, unit_id: int, channel_id: int) -> float | None:
        self._current_calls += 1
        if self.fail_on_current_call == self._current_calls:
            raise RuntimeError("Fake current data read failed.")

        samples = self.samples_by_channel[(unit_id, channel_id)]
        published_count = self.data_count
        if published_count == 0:
            return None
        self._extend_samples_to_index(samples, published_count - 1)
        return samples[published_count - 1]

    def _extend_samples_to_index(self, samples: list[float | None], index: int) -> None:
        while len(samples) <= index:
            previous = samples[-1]
            if previous is None:
                samples.append(None)
                continue
            next_value = previous + self._rng.uniform(-self.random_step, self.random_step)
            samples.append(max(0.0, next_value))


@dataclass
class FakeDeviceConnector:
    setup_calls: list[int] = field(default_factory=list)
    fail_on_setup: bool = False

    def setup_usb(self, device_id: int) -> None:
        self.setup_calls.append(device_id)
        if self.fail_on_setup:
            raise RuntimeError("Fake USB setup failed.")


@dataclass
class FakeMeasurementController:
    loaded_paths: list[str] = field(default_factory=list)
    started: bool = False
    stopped: bool = False
    fail_on_load: bool = False
    fail_on_start: bool = False

    def load_settings(self, path: Path | str) -> None:
        self.loaded_paths.append(str(path))
        if self.fail_on_load:
            raise RuntimeError("Fake settings load failed.")

    def start(self) -> None:
        if self.fail_on_start:
            raise RuntimeError("Fake measurement start failed.")
        self.started = True

    def stop(self) -> None:
        self.stopped = True


@dataclass
class FakeWaveLoggerApp:
    document: FakeWaveLoggerDocument
    connector: FakeDeviceConnector = field(default_factory=FakeDeviceConnector)
    measurement: FakeMeasurementController = field(default_factory=FakeMeasurementController)
    entered: bool = False
    exited: bool = False

    def get_active_document(self) -> FakeWaveLoggerDocument:
        return self.document

    def __enter__(self) -> "FakeWaveLoggerApp":
        self.entered = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.exited = True
        if self.measurement.started and not self.measurement.stopped:
            self.measurement.stop()
