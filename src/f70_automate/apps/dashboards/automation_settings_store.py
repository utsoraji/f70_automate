from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, cast

from f70_automate._core.config import ConfigError, parse_section, read_yaml, write_yaml
from f70_automate.domains.automation.settings import AutomationSettings
from f70_automate.domains.notification import NotificationSettings
from f70_automate.domains.wavelogger import ChannelConfig

DEFAULT_SETTINGS_PATH = Path("src/f70_automate/resources/automation_dashboard_settings.yaml")
DEFAULT_SERIAL_PORT = "COM3"
DEFAULT_SERIAL_BAUDRATE = 9600
DEFAULT_USE_MOCK_DEVICES = True


class DashboardSettingsError(ValueError):
    """Raised when dashboard settings file cannot be loaded or parsed."""


def _as_mapping(node: dict[str, Any]) -> dict[str, Any]:
    return node


def _to_string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise DashboardSettingsError("notification.slack_bot.mention_user_ids must be a list or comma-separated string")


def _to_automation_settings(
    node: dict[str, Any],
    *,
    channels: tuple[ChannelConfig, ...],
    default_operation_name: str,
) -> AutomationSettings:
    thresholds = node.get("thresholds_by_channel_key", {})
    if not isinstance(thresholds, dict):
        raise DashboardSettingsError("automation.thresholds_by_channel_key must be a mapping")

    return AutomationSettings(
        channels=channels,
        selected_channel_key=(
            str(node["selected_channel_key"]) if node.get("selected_channel_key") else None
        ),
        thresholds_by_channel_key={
            str(key): float(value) for key, value in thresholds.items()
        },
        required_sample_count=int(node.get("required_sample_count", 3)),
        cooldown_sec=float(node.get("cooldown_sec", 3.0)),
        operation_name=str(node.get("operation_name", default_operation_name)),
        notification_enabled=bool(node.get("notification_enabled", False)),
    )


def _to_notification_settings(node: dict[str, Any]) -> NotificationSettings:
    slack_node = node.get("slack_bot", {})
    if not isinstance(slack_node, dict):
        raise DashboardSettingsError("notification.slack_bot must be a mapping")

    raw_failure_policy = str(node.get("failure_policy", "best_effort"))
    if raw_failure_policy not in ("best_effort", "strict"):
        raise DashboardSettingsError("notification.failure_policy must be 'best_effort' or 'strict'")

    settings = NotificationSettings(
        failure_policy=cast(Literal["best_effort", "strict"], raw_failure_policy),
    )
    settings.slack_bot.enabled = bool(slack_node.get("enabled", False))
    settings.slack_bot.channel_id = str(slack_node.get("channel_id", ""))
    settings.slack_bot.channel_name = str(slack_node.get("channel_name", ""))
    raw_mention_user_ids = slack_node.get("mention_user_ids", ())
    settings.slack_bot.mention_user_ids = _to_string_tuple(raw_mention_user_ids)
    settings.slack_bot.token_env_key = str(slack_node.get("token_env_key", settings.slack_bot.token_env_key))
    settings.slack_bot.periodic_message_enabled = bool(slack_node.get("periodic_message_enabled", False))
    settings.slack_bot.periodic_message_interval_min = int(
        slack_node.get("periodic_message_interval_min", settings.slack_bot.periodic_message_interval_min)
    )
    if settings.slack_bot.periodic_message_interval_min < 1:
        raise DashboardSettingsError("notification.slack_bot.periodic_message_interval_min must be >= 1")

    return settings


def _automation_to_dict(settings: AutomationSettings) -> dict[str, Any]:
    return {
        "selected_channel_key": settings.selected_channel_key,
        "thresholds_by_channel_key": settings.thresholds_by_channel_key,
        "required_sample_count": settings.required_sample_count,
        "cooldown_sec": settings.cooldown_sec,
        "operation_name": settings.operation_name,
        "notification_enabled": settings.notification_enabled,
    }


def _notification_to_dict(settings: NotificationSettings) -> dict[str, Any]:
    return {
        "failure_policy": settings.failure_policy,
        "slack_bot": {
            "enabled": settings.slack_bot.enabled,
            "channel_id": settings.slack_bot.channel_id,
            "channel_name": settings.slack_bot.channel_name,
            "mention_user_ids": list(settings.slack_bot.mention_user_ids),
            "token_env_key": settings.slack_bot.token_env_key,
            "periodic_message_enabled": settings.slack_bot.periodic_message_enabled,
            "periodic_message_interval_min": settings.slack_bot.periodic_message_interval_min,
        },
    }


def _extract_serial_settings(payload: dict[str, Any]) -> tuple[str, int, bool]:
    app_node = payload.get("app", {})
    if not isinstance(app_node, dict):
        return DEFAULT_SERIAL_PORT, DEFAULT_SERIAL_BAUDRATE, DEFAULT_USE_MOCK_DEVICES

    app_settings_node = app_node.get("settings", {})
    if isinstance(app_settings_node, dict):
        use_mock_devices = bool(app_settings_node.get("use_mock_devices", DEFAULT_USE_MOCK_DEVICES))
    else:
        use_mock_devices = DEFAULT_USE_MOCK_DEVICES

    serial_node = app_node.get("serial", {})
    if not isinstance(serial_node, dict):
        return DEFAULT_SERIAL_PORT, DEFAULT_SERIAL_BAUDRATE, use_mock_devices

    settings_node = serial_node.get("settings", {})
    if not isinstance(settings_node, dict):
        return DEFAULT_SERIAL_PORT, DEFAULT_SERIAL_BAUDRATE, use_mock_devices

    return (
        str(settings_node["port"]),
        int(settings_node["baudrate"]),
        use_mock_devices,
    )


def load_dashboard_settings(
    *,
    channels: tuple[ChannelConfig, ...],
    default_operation_name: str,
    path: Path = DEFAULT_SETTINGS_PATH,
) -> tuple[AutomationSettings, NotificationSettings, str, int, bool]:
    if not path.exists():
        return (
            AutomationSettings(channels=channels, operation_name=default_operation_name),
            NotificationSettings(),
            DEFAULT_SERIAL_PORT,
            DEFAULT_SERIAL_BAUDRATE,
            DEFAULT_USE_MOCK_DEVICES,
        )

    try:
        payload = read_yaml(path)
        automation_node = parse_section(payload, ("app", "automation", "settings"), _as_mapping)
        notification_node = parse_section(payload, ("app", "notification", "settings"), _as_mapping)
        return (
            _to_automation_settings(
                automation_node,
                channels=channels,
                default_operation_name=default_operation_name,
            ),
            _to_notification_settings(notification_node),
            *_extract_serial_settings(payload),
        )
    except (ConfigError, ValueError, KeyError, TypeError) as exc:
        raise DashboardSettingsError(f"Failed to load dashboard settings: {exc}") from exc


def save_dashboard_settings(
    *,
    path: Path,
    settings: AutomationSettings,
    notification_settings: NotificationSettings,
    serial_port: str,
    serial_baudrate: int,
    use_mock_devices: bool,
) -> None:
    payload: dict[str, Any] = {
        "app": {
            "settings": {
                "use_mock_devices": use_mock_devices,
            },
            "automation": {
                "settings": _automation_to_dict(settings),
            },
            "notification": {
                "settings": _notification_to_dict(notification_settings),
            },
            "serial": {
                "settings": {
                    "port": serial_port,
                    "baudrate": serial_baudrate,
                }
            },
        }
    }
    write_yaml(path, payload)
