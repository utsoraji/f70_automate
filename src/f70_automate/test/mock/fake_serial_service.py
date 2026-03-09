from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from f70_automate.test.mock.fake_serial import FakeSerial
from f70_automate.test.mock.fake_serial_f70 import F70Responder


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

    def call_checked(self, op: Any, *a: Any, **kw: Any) -> Any:
        if not callable(op):
            raise TypeError("op must be callable.")
        if not hasattr(op, "can_execute"):
            raise TypeError("op must implement can_execute(ser).")
        if not op.can_execute(self._serial):
            op_name = getattr(op, "name", repr(op))
            raise RuntimeError(f"Operation '{op_name}' cannot execute in current state.")
        return op(self._serial, *a, **kw)

    def close(self) -> None:
        self.shutdown()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._serial.close()
        self._closed = True
