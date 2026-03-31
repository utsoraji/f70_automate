from __future__ import annotations

from f70_automate.domains.notification.adapters import (
    SlackBotNotificationConfig,
    SlackBotNotifier,
)
from f70_automate.domains.notification.dispatch import FanoutNotificationDispatcher
from f70_automate.domains.notification.protocols import NotificationDispatcher
from f70_automate.domains.notification.settings import NotificationSettings


def _parse_csv_values(values: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in values.split(",") if item.strip())


def _build_slack_notifier(
    settings: NotificationSettings,
    *,
    include_mentions: bool,
) -> SlackBotNotifier | None:
    if not settings.slack_bot.enabled:
        return None

    mention_user_ids = settings.slack_bot.mention_user_ids if include_mentions else ()
    return SlackBotNotifier(
        config=SlackBotNotificationConfig(
            channel_id=settings.slack_bot.channel_id,
            channel_name=settings.slack_bot.channel_name,
            mention_user_ids=mention_user_ids,
            token_env_key=settings.slack_bot.token_env_key,
        )
    )


def build_notification_dispatcher(
    *,
    enabled: bool,
    settings: NotificationSettings,
    include_mentions: bool = True,
) -> NotificationDispatcher | None:
    if not enabled:
        return None

    channels = []

    slack_notifier = _build_slack_notifier(
        settings,
        include_mentions=include_mentions,
    )
    if slack_notifier is not None:
        channels.append(slack_notifier)

    if not channels:
        return None
    return FanoutNotificationDispatcher(channels=tuple(channels), continue_on_error=True)
