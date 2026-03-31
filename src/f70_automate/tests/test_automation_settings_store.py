from __future__ import annotations

from pathlib import Path
import unittest

from f70_automate.apps.dashboards.automation_settings_store import (
    load_dashboard_settings,
    save_dashboard_settings,
)
from f70_automate.domains.automation.settings import AutomationSettings
from f70_automate.domains.notification import NotificationSettings
from f70_automate.domains.wavelogger.channel_config import ChannelConfig


class TestAutomationSettingsStore(unittest.TestCase):
    def setUp(self) -> None:
        self.channels = (
            ChannelConfig(
                key="ch_pressure",
                label="Pressure",
                unit_id=1,
                channel_id=0,
                unit="Pa",
            ),
            ChannelConfig(
                key="ch_temperature",
                label="Temperature",
                unit_id=1,
                channel_id=1,
                unit="K",
            ),
        )
        self.path = Path("src/f70_automate/tests/automation_dashboard_settings_test.yaml")

    def tearDown(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def test_load_returns_defaults_when_file_missing(self) -> None:
        settings, notification_settings = load_dashboard_settings(
            channels=self.channels,
            default_operation_name="no_op",
            path=self.path,
        )

        self.assertIsInstance(settings, AutomationSettings)
        self.assertIsInstance(notification_settings, NotificationSettings)
        self.assertEqual(settings.operation_name, "no_op")

    def test_round_trip_save_and_load(self) -> None:
        settings = AutomationSettings(
            channels=self.channels,
            selected_channel_key="ch_temperature",
            thresholds_by_channel_key={"ch_temperature": 0.25},
            required_sample_count=5,
            cooldown_sec=12.5,
            operation_name="power_off",
            notification_enabled=True,
        )
        notification_settings = NotificationSettings(failure_policy="strict")
        notification_settings.slack_bot.enabled = True
        notification_settings.slack_bot.channel_id = "C123"
        notification_settings.slack_bot.mention_user_ids = ("U111", "U222")
        notification_settings.slack_bot.token_env_key = "CUSTOM_SLACK_TOKEN"
        notification_settings.slack_bot.periodic_message_enabled = True
        notification_settings.slack_bot.periodic_message_interval_min = 45

        save_dashboard_settings(
            path=self.path,
            settings=settings,
            notification_settings=notification_settings,
        )
        loaded_settings, loaded_notification_settings = load_dashboard_settings(
            channels=self.channels,
            default_operation_name="no_op",
            path=self.path,
        )

        self.assertEqual(loaded_settings.selected_channel_key, "ch_temperature")
        self.assertEqual(loaded_settings.required_sample_count, 5)
        self.assertEqual(loaded_settings.cooldown_sec, 12.5)
        self.assertEqual(loaded_settings.operation_name, "power_off")
        self.assertTrue(loaded_settings.notification_enabled)
        self.assertEqual(
            loaded_settings.thresholds_by_channel_key["ch_temperature"],
            0.25,
        )

        self.assertEqual(loaded_notification_settings.failure_policy, "strict")
        self.assertTrue(loaded_notification_settings.slack_bot.enabled)
        self.assertEqual(loaded_notification_settings.slack_bot.channel_id, "C123")
        self.assertEqual(
            loaded_notification_settings.slack_bot.mention_user_ids,
            ("U111", "U222"),
        )
        self.assertEqual(
            loaded_notification_settings.slack_bot.token_env_key,
            "CUSTOM_SLACK_TOKEN",
        )
        self.assertTrue(loaded_notification_settings.slack_bot.periodic_message_enabled)
        self.assertEqual(
            loaded_notification_settings.slack_bot.periodic_message_interval_min,
            45,
        )


if __name__ == "__main__":
    unittest.main()
