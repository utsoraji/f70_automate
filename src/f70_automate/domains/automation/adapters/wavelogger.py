from __future__ import annotations

import queue
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from f70_automate.domains.automation.monitoring import EventStream, ValueEvent
from f70_automate.domains.wavelogger.channel_config import ChannelConfig
from f70_automate.domains.wavelogger.wlx_thread import PhysicalSampleBatch


class PhysicalSamplePublisherLike(Protocol):
    def add_physical_listener(self, listener: "PhysicalSampleListener") -> None: ...

    def remove_physical_listener(self, listener: "PhysicalSampleListener") -> None: ...


class PhysicalSampleListener(Protocol):
    def __call__(self, batch: PhysicalSampleBatch) -> None: ...


@dataclass
class ChannelValueStream(EventStream[float]):
    logger: PhysicalSamplePublisherLike
    channel: ChannelConfig
    _events: queue.SimpleQueue[ValueEvent[float] | None] = field(default_factory=queue.SimpleQueue, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.logger.add_physical_listener(self._handle_sample)

    def get(self) -> ValueEvent[float] | None:
        return self._events.get()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.logger.remove_physical_listener(self._handle_sample)
        self._events.put(None)

    def _handle_sample(self, batch: PhysicalSampleBatch) -> None:
        if self._closed:
            return
        for channel, value in batch.physical_values:
            if channel.key != self.channel.key:
                continue
            self._events.put(
                ValueEvent(value=value, occurred_at=datetime.fromtimestamp(batch.received_at))
            )
            break
