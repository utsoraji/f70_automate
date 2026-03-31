from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
import os

from f70_automate.domains.notification.models import NotificationMessage
from f70_automate.domains.notification.protocols import NotificationChannel


class SlackWebClientLike(Protocol):
    def chat_postMessage(self, *, channel: str, text: str | None = None) -> object: ...

    def conversations_list(
        self,
        *,
        types: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> object: ...


class SlackWebClientFactory(Protocol):
    def __call__(self, token: str) -> SlackWebClientLike: ...


class SlackWebClientAdapter(SlackWebClientLike):
    def __init__(self, token: str):
        from slack_sdk import WebClient

        self._client = WebClient(token=token)

    def chat_postMessage(self, *, channel: str, text: str | None = None) -> object:
        return self._client.chat_postMessage(channel=channel, text=text)

    def conversations_list(
        self,
        *,
        types: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> object:
        return self._client.conversations_list(types=types, limit=limit, cursor=cursor)


def default_slack_client_factory(token: str) -> SlackWebClientLike:
    return SlackWebClientAdapter(token=token)


@dataclass(frozen=True)
class SlackBotNotificationConfig:
    channel_id: str = ""
    channel_name: str = ""
    mention_user_ids: tuple[str, ...] = ()
    token_env_key: str = "F70_SLACK_BOT_TOKEN"


@dataclass
class SlackBotNotifier(NotificationChannel):
    config: SlackBotNotificationConfig
    client_factory: SlackWebClientFactory = default_slack_client_factory

    def send(self, message: NotificationMessage) -> None:
        token = os.getenv(self.config.token_env_key, "")
        if not token:
            raise ValueError(f"Slack bot token is missing. Set env var: {self.config.token_env_key}")

        client = self.client_factory(token)
        channel_id = self._resolve_channel_id(client)
        text = self._build_message_text(message)
        client.chat_postMessage(channel=channel_id, text=text)

    def _build_message_text(self, message: NotificationMessage) -> str:
        mention_prefix = " ".join(f"<@{user_id}>" for user_id in self.config.mention_user_ids)
        body = f"*{message.title}*\n{message.body}"
        if not mention_prefix:
            return body
        return f"{mention_prefix}\n{body}"

    def _resolve_channel_id(self, client: SlackWebClientLike) -> str:
        if self.config.channel_id:
            return self.config.channel_id
        if not self.config.channel_name:
            raise ValueError("Slack channel_id or channel_name is required.")

        # Resolve by name when operator prefers human-readable channel input.
        cursor: str | None = None
        while True:
            response = client.conversations_list(
                types="public_channel,private_channel",
                limit=200,
                cursor=cursor,
            )
            channels = _read_channels(response)
            for channel in channels:
                if channel.get("name") == self.config.channel_name:
                    channel_id = channel.get("id")
                    if isinstance(channel_id, str) and channel_id:
                        return channel_id

            cursor = _read_next_cursor(response)
            if not cursor:
                break

        raise ValueError(f"Slack channel_name not found: {self.config.channel_name}")


def _read_channels(response: object) -> list[dict[str, object]]:
    data = getattr(response, "data", response)
    if not isinstance(data, dict):
        return []
    channels = data.get("channels")
    if not isinstance(channels, list):
        return []
    return [item for item in channels if isinstance(item, dict)]


def _read_next_cursor(response: object) -> str | None:
    data = getattr(response, "data", response)
    if not isinstance(data, dict):
        return None
    metadata = data.get("response_metadata")
    if not isinstance(metadata, dict):
        return None
    cursor = metadata.get("next_cursor")
    if isinstance(cursor, str) and cursor:
        return cursor
    return None


if TYPE_CHECKING:
    _: SlackWebClientLike = SlackWebClientAdapter(token="xoxb-dummy")
