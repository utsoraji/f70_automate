from __future__ import annotations

from typing import Protocol

from f70_automate.domains.notification.models import NotificationMessage


class NotificationChannel(Protocol):
    def send(self, message: NotificationMessage) -> None: ...


class NotificationDispatcher(Protocol):
    def dispatch(self, message: NotificationMessage) -> None: ...
