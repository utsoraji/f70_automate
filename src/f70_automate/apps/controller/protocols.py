from __future__ import annotations

from typing import Callable, Concatenate, ParamSpec, Protocol, TypeVar

from f70_automate._core.serial.serial_async import SerialPortLike
from f70_automate._core.serial.serial_service import CallableWithCanExecute
from f70_automate.domains.wavelogger import ChannelConfig
from f70_automate.domains.automation.adapters.wavelogger import PhysicalSamplePublisherLike

P = ParamSpec("P")
R = TypeVar("R", covariant=True)


class SerialServiceLike(Protocol):
    @property
    def is_alive(self) -> bool: ...

    @property
    def closed(self) -> bool: ...

    def call(self, fn: Callable[Concatenate[SerialPortLike, P], R], *a: P.args, **kw: P.kwargs) -> R: ...

    __call__ = call

    def call_checked(self, operation: CallableWithCanExecute[P, R]) -> R: ...

    def shutdown(self) -> None: ...


class WaveRuntimeStoreLike(Protocol):
    def get_current_physical(self, channel: ChannelConfig) -> float | None: ...

    def check_exception(self) -> None: ...


class WaveRuntimeRunnerLike(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def is_alive(self) -> bool: ...


class WaveRuntimeLike(Protocol):
    @property
    def store(self) -> WaveRuntimeStoreLike: ...

    @property
    def runner(self) -> WaveRuntimeRunnerLike: ...

    @property
    def publisher(self) -> PhysicalSamplePublisherLike: ...


class ServiceRepository(Protocol):
    def get_serial(self, port: str, baudrate: int, use_mock: bool) -> SerialServiceLike: ...

    def reset_serial(self, port: str, baudrate: int, use_mock: bool) -> None: ...

    def get_runtime(self, use_mock: bool) -> WaveRuntimeLike: ...

    def reset_runtime(self, use_mock: bool) -> None: ...
