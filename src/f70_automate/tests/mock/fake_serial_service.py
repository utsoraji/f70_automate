from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from f70_automate._core.serial.serial_service import CallableWithCanExecute
from f70_automate.tests.mock.fake_serial import FakeSerial
from f70_automate.tests.mock.fake_serial_f70 import F70Responder


@dataclass
class FakeSerialService:
    responder: F70Responder = field(default_factory=F70Responder)
    port: str = "FAKE"
    baudrate: int = 9600

    def __post_init__(self) -> None:
        self._serial = FakeSerial(
            responder=self.responder,
            port=self.port,
            baudrate=self.baudrate,
        )
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def is_alive(self) -> bool:
        return not self._closed and self._serial.is_open

    def call(self, fn: Callable[..., Any], *a: Any, **kw: Any) -> Any:
        if self._closed:
            raise RuntimeError("FakeSerialService is closed.")
        return fn(self._serial, *a, **kw)

    __call__ = call

    def call_checked(self, operation: CallableWithCanExecute, *a: Any, **kw: Any) -> Any:
        if not callable(operation):
            raise TypeError("operation must be callable.")
        if not hasattr(operation, "can_execute"):
            raise TypeError("operation must implement can_execute(ser).")
        if not operation.can_execute(self._serial):
            op_name = getattr(operation, "name", repr(operation))
            raise RuntimeError(f"Operation '{op_name}' cannot execute in current state.")
        return operation(self._serial, *a, **kw)

    def close(self) -> None:
        self.shutdown()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._serial.close()
        self._closed = True
