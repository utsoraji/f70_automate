from __future__ import annotations

from dataclasses import dataclass

from f70_automate.domains.notification.models import NotificationMessage
from f70_automate.domains.notification.protocols import NotificationChannel, NotificationDispatcher


class NotificationDispatchError(Exception):
    def __init__(self, errors: tuple[Exception, ...]):
        self.errors = errors
        details = "; ".join(str(error) for error in errors)
        super().__init__(f"Notification dispatch failed: {details}")


@dataclass
class FanoutNotificationDispatcher(NotificationDispatcher):
    channels: tuple[NotificationChannel, ...]
    continue_on_error: bool = True

    def dispatch(self, message: NotificationMessage) -> None:
        errors: list[Exception] = []
        for channel in self.channels:
            try:
                channel.send(message)
            except Exception as exc:
                errors.append(exc)
                if not self.continue_on_error:
                    raise
        if errors:
            raise NotificationDispatchError(tuple(errors))


@dataclass
class NoOpNotificationDispatcher(NotificationDispatcher):
    def dispatch(self, message: NotificationMessage) -> None:
        _ = message
