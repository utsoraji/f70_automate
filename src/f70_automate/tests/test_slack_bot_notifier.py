from __future__ import annotations

from datetime import datetime
import os
import unittest

from f70_automate.domains.notification.adapters.slack_bot import (
    SlackBotNotificationConfig,
    SlackBotNotifier,
)
from f70_automate.domains.notification.models import NotificationMessage


class _FakeSlackClient:
    def __init__(self) -> None:
        self.posted: list[tuple[str, str | None]] = []
        self.pages: list[dict[str, object]] = []

    def chat_postMessage(self, *, channel: str, text: str | None = None) -> object:
        self.posted.append((channel, text))
        return {"ok": True}

    def conversations_list(
        self,
        *,
        types: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> object:
        _ = types
        _ = limit
        if cursor is None:
            index = 0
        else:
            index = int(cursor)
        if index >= len(self.pages):
            return {"channels": [], "response_metadata": {"next_cursor": ""}}
        return self.pages[index]


class TestSlackBotNotifier(unittest.TestCase):
    def setUp(self) -> None:
        self.env_key = "F70_TEST_SLACK_BOT_TOKEN"
        os.environ[self.env_key] = "xoxb-test"
        self.message = NotificationMessage(
            title="Triggered",
            body="automation fired",
            occurred_at=datetime.fromtimestamp(100.0),
        )

    def tearDown(self) -> None:
        os.environ.pop(self.env_key, None)

    def test_send_uses_channel_id_directly(self):
        client = _FakeSlackClient()
        notifier = SlackBotNotifier(
            config=SlackBotNotificationConfig(channel_id="C123", token_env_key=self.env_key),
            client_factory=lambda token: client,
        )

        notifier.send(self.message)

        self.assertEqual(client.posted, [("C123", "*Triggered*\nautomation fired")])

    def test_send_resolves_channel_name(self):
        client = _FakeSlackClient()
        client.pages = [
            {
                "channels": [
                    {"id": "C111", "name": "random"},
                    {"id": "C222", "name": "alerts"},
                ],
                "response_metadata": {"next_cursor": ""},
            }
        ]
        notifier = SlackBotNotifier(
            config=SlackBotNotificationConfig(channel_name="alerts", token_env_key=self.env_key),
            client_factory=lambda token: client,
        )

        notifier.send(self.message)

        self.assertEqual(client.posted, [("C222", "*Triggered*\nautomation fired")])

    def test_send_prefixes_user_mentions(self):
        client = _FakeSlackClient()
        notifier = SlackBotNotifier(
            config=SlackBotNotificationConfig(
                channel_id="C123",
                mention_user_ids=("U111", "U222"),
                token_env_key=self.env_key,
            ),
            client_factory=lambda token: client,
        )

        notifier.send(self.message)

        self.assertEqual(
            client.posted,
            [("C123", "<@U111> <@U222>\n*Triggered*\nautomation fired")],
        )

    def test_send_raises_when_channel_name_not_found(self):
        client = _FakeSlackClient()
        client.pages = [
            {
                "channels": [{"id": "C111", "name": "random"}],
                "response_metadata": {"next_cursor": ""},
            }
        ]
        notifier = SlackBotNotifier(
            config=SlackBotNotificationConfig(channel_name="alerts", token_env_key=self.env_key),
            client_factory=lambda token: client,
        )

        with self.assertRaisesRegex(ValueError, "channel_name not found"):
            notifier.send(self.message)


if __name__ == "__main__":
    unittest.main()
