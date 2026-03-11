from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from f70_automate.domains.automation.monitoring import Trigger
from f70_automate.domains.f70_serial.f70_operation import F70Operation


class OperationExecutorLike(Protocol):
    @property
    def closed(self) -> bool: ...

    @property
    def is_alive(self) -> bool: ...

    def __call__(self, *args: Any, **kwds: Any) -> None: ...
    def call_checked(self, operation: F70Operation) -> None: ...



@dataclass
class OperationTrigger(Trigger[F70Operation]):
    service: OperationExecutorLike
    operation: F70Operation

    def fire(self) -> F70Operation:
        self.service.call_checked(self.operation)
        return self.operation
