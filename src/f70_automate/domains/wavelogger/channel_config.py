from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import math
from pathlib import Path

import yaml


class TransformKind(StrEnum):
    LINEAR = "linear"
    LOG10_EXP = "log10_exp"

ChannelConfigDict = dict[str, str | int | float]

@dataclass(frozen=True)
class ChannelConfig:
    key: str
    label: str
    unit_id: int
    channel_id: int
    transform: TransformKind = TransformKind.LINEAR
    scale: float = 1.0
    offset: float = 0.0
    unit: str = "V"

    def voltage_to_physical(self, voltage: float | None) -> float | None:
        if voltage is None:
            return None
        if self.transform == TransformKind.LINEAR:
            return (self.scale * voltage) + self.offset
        if self.transform == TransformKind.LOG10_EXP:
            return math.pow(10.0, (self.scale * voltage) + self.offset)
        raise ValueError(f"Unsupported transform: {self.transform}")

    def to_dict(self) -> ChannelConfigDict:
        data = asdict(self)
        data["transform"] = self.transform.value
        return data

    @classmethod
    def from_dict(cls, data: ChannelConfigDict) -> "ChannelConfig":
        return cls(
            key=str(data["key"]),
            label=str(data["label"]),
            unit_id=int(data["unit_id"]),
            channel_id=int(data["channel_id"]),
            transform=TransformKind(data.get("transform", TransformKind.LINEAR.value)),
            scale=float(data.get("scale", 1.0)),
            offset=float(data.get("offset", 0.0)),
            unit=str(data.get("unit", "V")),
        )

    def __str__(self) -> str:
        return self.label


def dump_channel_configs(configs: tuple[ChannelConfig, ...] | list[ChannelConfig]) -> str:
    payload = {"channels": [config.to_dict() for config in configs]}
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def load_channel_configs(text: str) -> tuple[ChannelConfig, ...]:
    payload = yaml.safe_load(text) or {}
    raw_channels = payload.get("channels", [])
    return tuple(ChannelConfig.from_dict(item) for item in raw_channels)


def save_channel_configs(path: Path | str, configs: tuple[ChannelConfig, ...] | list[ChannelConfig]) -> None:
    Path(path).write_text(dump_channel_configs(configs), encoding="utf-8")


def read_channel_configs(path: Path | str) -> tuple[ChannelConfig, ...]:
    return load_channel_configs(Path(path).read_text(encoding="utf-8"))
