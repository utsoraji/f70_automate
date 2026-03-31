from __future__ import annotations

import os
from typing import Literal, cast

import streamlit as st

from f70_automate.domains.automation.settings import AutomationSettings
from f70_automate.domains.f70_serial.f70_operation import F70Operation
from f70_automate.domains.notification import NotificationSettings
from f70_automate.domains.wavelogger import ChannelConfig


def _env_status_label(env_key: str) -> str:
    value = os.getenv(env_key, "")
    return "present" if bool(value) else "missing"


def _format_csv(values: tuple[str, ...]) -> str:
    return ", ".join(values)


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def render_settings_panel(
    *,
    use_mock: bool,
    settings: AutomationSettings,
    notification_settings: NotificationSettings,
    automation_operations: tuple[F70Operation, ...],
    wavelogger_channels: tuple[ChannelConfig, ...],
    monitor_running: bool,
) -> tuple[str, int, F70Operation]:
    with st.container(border=True):
        st.subheader("Automation Settings")
        tab_automation, tab_notification = st.tabs(["Automation", "Notification"])

        with tab_automation:
            top_row1, top_row2, top_row3 = st.columns(3)
            with top_row1:
                default_port = "MOCK" if use_mock else "COM3"
                port = st.text_input("F70 COM Port", value=default_port, disabled=use_mock)
            with top_row2:
                baudrate = int(
                    st.number_input(
                        "Baudrate",
                        min_value=1200,
                        max_value=115200,
                        value=9600,
                        step=1200,
                    )
                )
            with top_row3:
                selected_channel = next(
                    channel
                    for channel in wavelogger_channels
                    if channel.key == settings.selected_channel_key
                )
                selected_channel = cast(
                    ChannelConfig,
                    st.selectbox(
                        "Automation Input",
                        options=wavelogger_channels,
                        index=next(
                            i
                            for i, channel in enumerate(wavelogger_channels)
                            if channel.key == settings.selected_channel_key
                        ),
                        format_func=lambda channel: channel.label,
                        disabled=monitor_running,
                    ),
                )
                settings.selected_channel_key = selected_channel.key

            bottom_row1, bottom_row2, bottom_row3 = st.columns(3)
            with bottom_row1:
                threshold = st.number_input(
                    f"Trigger Threshold [{selected_channel.unit}]",
                    value=float(settings.threshold),
                    step=0.01,
                    format="%.3f",
                    disabled=monitor_running,
                )
                settings.threshold = float(threshold)
            with bottom_row2:
                sample_count = st.number_input(
                    "Samples to Judge",
                    min_value=1,
                    value=int(settings.required_sample_count),
                    step=1,
                    disabled=monitor_running,
                )
                settings.required_sample_count = int(sample_count)
            with bottom_row3:
                cooldown_sec = st.number_input(
                    "Cooldown [sec]",
                    min_value=0.0,
                    value=float(settings.cooldown_sec),
                    step=0.5,
                    disabled=monitor_running,
                )
                settings.cooldown_sec = float(cooldown_sec)

            operation = cast(
                F70Operation,
                st.selectbox(
                    "Command when physical value < threshold",
                    options=automation_operations,
                    index=next(
                        i
                        for i, candidate in enumerate(automation_operations)
                        if candidate.name == settings.operation_name
                    ),
                    format_func=lambda candidate: candidate.name,
                    disabled=monitor_running,
                ),
            )
            settings.operation_name = operation.name
            st.caption(f"Threshold is interpreted as {selected_channel.unit}.")

        with tab_notification:
            settings.notification_enabled = st.toggle(
                "Notify when automation triggers",
                value=settings.notification_enabled,
                disabled=monitor_running,
            )
            notification_settings.failure_policy = cast(
                Literal["best_effort", "strict"],
                st.selectbox(
                    "Failure policy",
                    options=("best_effort", "strict"),
                    index=0 if notification_settings.failure_policy == "best_effort" else 1,
                    disabled=monitor_running,
                ),
            )

            st.markdown("**Slack App Bot**")
            notification_settings.slack_bot.enabled = st.toggle(
                "Enable Slack Bot notification",
                value=notification_settings.slack_bot.enabled,
                disabled=monitor_running,
            )
            notification_settings.slack_bot.channel_id = st.text_input(
                "Slack Channel ID (e.g. C0123456789)",
                value=notification_settings.slack_bot.channel_id,
                disabled=monitor_running,
            )
            notification_settings.slack_bot.channel_name = st.text_input(
                "Slack Channel Name (ID未入力時に使用)",
                value=notification_settings.slack_bot.channel_name,
                disabled=monitor_running,
            )
            mention_user_ids = st.text_input(
                "Slack Mention User IDs (comma separated)",
                value=_format_csv(notification_settings.slack_bot.mention_user_ids),
                disabled=monitor_running,
                help="Use Slack user IDs like U0123456789. Mention is added at the top of the message.",
            )
            notification_settings.slack_bot.mention_user_ids = _parse_csv(mention_user_ids)
            notification_settings.slack_bot.token_env_key = st.text_input(
                "Slack Bot Token env key",
                value=notification_settings.slack_bot.token_env_key,
                disabled=monitor_running,
            )
            notification_settings.slack_bot.periodic_message_enabled = st.toggle(
                "Enable periodic Slack status message",
                value=notification_settings.slack_bot.periodic_message_enabled,
                disabled=monitor_running,
            )
            notification_settings.slack_bot.periodic_message_interval_min = int(
                st.number_input(
                    "Periodic message interval [min]",
                    min_value=1,
                    value=int(notification_settings.slack_bot.periodic_message_interval_min),
                    step=1,
                    disabled=monitor_running or not notification_settings.slack_bot.periodic_message_enabled,
                )
            )

            st.markdown("**Secrets Status**")
            st.caption("Environment variable values are never displayed; only presence is checked.")
            st.metric(
                notification_settings.slack_bot.token_env_key,
                _env_status_label(notification_settings.slack_bot.token_env_key),
            )

    return port, baudrate, operation
