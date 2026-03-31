from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, ParamSpec, Protocol, TypeVar

from f70_automate.domains.automation.monitoring import Trigger
from f70_automate.domains.f70_serial.f70_operation import F70Operation
from f70_automate.domains.notification import NotificationDispatcher, NotificationMessage

P = ParamSpec("P")
R = TypeVar("R", covariant=True)

class OperationExecutorLike(Protocol[P, R]):
    @property
    def closed(self) -> bool: ...

    @property
    def is_alive(self) -> bool: ...

    def __call__(self, *args: P.args, **kwds: P.kwargs) -> R: ...
    def call_checked(self, operation: F70Operation) -> R: ...



@dataclass
class OperationTrigger(Trigger[F70Operation]):
    service: OperationExecutorLike
    operation: F70Operation

    def fire(self) -> F70Operation:
        self.service.call_checked(self.operation)
        return self.operation


@dataclass
class NotifyingOperationTrigger(Trigger[F70Operation]):
    service: OperationExecutorLike
    operation: F70Operation
    notification_dispatcher: NotificationDispatcher | None = None
    notification_message_factory: Callable[[F70Operation], NotificationMessage] | None = None
    notification_failure_policy: Literal["best_effort", "strict"] = "best_effort"

    def fire(self) -> F70Operation:
        self.service.call_checked(self.operation)
        if self.notification_dispatcher is None or self.notification_message_factory is None:
            return self.operation

        message = self.notification_message_factory(self.operation)
        try:
            self.notification_dispatcher.dispatch(message)
        except Exception:
            if self.notification_failure_policy == "strict":
                raise
        return self.operation
