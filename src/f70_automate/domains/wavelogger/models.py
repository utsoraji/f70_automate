from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from f70_automate.domains.wavelogger.channel_config import ChannelConfig


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
