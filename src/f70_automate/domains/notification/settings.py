from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SlackBotSettings:
    enabled: bool = False
    channel_id: str = ""
    channel_name: str = ""
    mention_user_ids: tuple[str, ...] = ()
    token_env_key: str = "F70_SLACK_BOT_TOKEN"
    periodic_message_enabled: bool = False
    periodic_message_interval_min: int = 30


@dataclass
class NotificationSettings:
    failure_policy: Literal["best_effort", "strict"] = "best_effort"
    slack_bot: SlackBotSettings = field(default_factory=SlackBotSettings)

    def __post_init__(self) -> None:
        if self.failure_policy not in ("best_effort", "strict"):
            raise ValueError("failure_policy must be 'best_effort' or 'strict'.")
        if self.slack_bot.periodic_message_interval_min < 1:
            raise ValueError("slack_bot.periodic_message_interval_min must be >= 1.")
