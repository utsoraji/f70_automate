from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from f70_automate.domains.wavelogger.channel_config import ChannelConfig


def get_channel_by_key(channels: tuple[ChannelConfig, ...], channel_key: str) -> ChannelConfig:
    return next(channel for channel in channels if channel.key == channel_key)


def default_thresholds_by_channel(
    channels: tuple[ChannelConfig, ...],
    default_threshold: float = 0.1,
) -> dict[str, float]:
    return {channel.key: default_threshold for channel in channels}


@dataclass
class AutomationSettings:
    channels: tuple[ChannelConfig, ...]
    selected_channel_key: str | None = None
    thresholds_by_channel_key: dict[str, float] = field(default_factory=dict)
    required_sample_count: int = 3
    cooldown_sec: float = 3.0
    operation_name: str = ""

    def __post_init__(self) -> None:
        if not self.channels:
            raise ValueError("At least one channel must be configured.")
        if self.required_sample_count < 1:
            raise ValueError("required_sample_count must be >= 1.")
        if self.selected_channel_key is None:
            self.selected_channel_key = self.channels[0].key
        self.thresholds_by_channel_key = (
            default_thresholds_by_channel(self.channels) | self.thresholds_by_channel_key
        )

    @property
    def selected_channel(self) -> ChannelConfig:
        return get_channel_by_key(self.channels, cast(str, self.selected_channel_key))

    @property
    def threshold(self) -> float:
        return self.thresholds_by_channel_key[self.selected_channel.key]

    @threshold.setter
    def threshold(self, value: float) -> None:
        self.thresholds_by_channel_key[self.selected_channel.key] = value
