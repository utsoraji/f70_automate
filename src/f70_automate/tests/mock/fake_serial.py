from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol


class Responder(Protocol):
    def __call__(self, request: bytes) -> bytes: ...


@dataclass
class FakeSerial:
    responder: Responder
    port: str = "FAKE"
    baudrate: int = 9600
    is_open: bool = True
    _pending: bytes = b""
    writes: list[bytes] = field(default_factory=list)

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise RuntimeError("Port is closed")
        self.writes.append(data)
        # 1 request -> 1 response
        self._pending = self.responder(data)
        return len(data)

    def read_until(self, expected: bytes = b"\r", size: int = 256) -> bytes:
        if not self.is_open:
            raise RuntimeError("Port is closed")
        out = self._pending[:size]
        self._pending = self._pending[size:]
        return out

    def close(self) -> None:
        self.is_open = False
