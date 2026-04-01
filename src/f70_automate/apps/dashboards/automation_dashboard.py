from typing import cast

import pandas as pd
import streamlit as st

from f70_automate._core.logging.models import LogLevel
from f70_automate.apps.controller.automation_usecase import (
    DashboardState,
    PeriodicNotificationRunner,
    SerialServiceLike,
    action_mode_changed,
    action_toggle_automation,
    action_toggle_wave,
    automation_ready,
    build_periodic_message_factory,
    build_trigger_message_factory,
    format_monitor_error,
    format_trigger_result,
    get_active_alarm_names,
    get_automation_operations,
    get_monitor_snapshot,
    load_automation_channels,
    read_f70_status,
    reconnect_f70,
    stop_periodic_notification_runner,
)
from f70_automate.apps.dashboards.automation_settings_ui import render_settings_panel
from f70_automate.apps.dashboards.automation_settings_store import (
    DEFAULT_SETTINGS_PATH,
    load_dashboard_settings,
    save_dashboard_settings,
)
from f70_automate.apps.dashboards.f70_command_console_component import render_f70_command_console_component
from f70_automate._core.config import load_dotenv_file
from f70_automate._core.logging import get_app_logger
from f70_automate.apps.dashboards.logging_subscribers import StreamlitConsoleSubscriber
import f70_automate.resources as local_resources
from f70_automate.domains.automation.monitoring import (
    ThreadedMonitorRunner,
)
from f70_automate.domains.automation.settings import AutomationSettings
from f70_automate.domains.notification import NotificationSettings, build_notification_dispatcher
from f70_automate._core.serial import SerialService
from f70_automate.tests.mock.fake_serial_f70 import F70Responder
from f70_automate.tests.mock.fake_serial_service import FakeSerialService
from f70_automate.tests.mock.fake_wavelogger import FakeWaveLoggerApp, FakeWaveLoggerDocument
from f70_automate.domains.wavelogger import WLXRuntime


WAVELOGGER_CHANNELS = load_automation_channels(local_resources.get_path("channel_configs.yaml"))
AUTOMATION_OPERATIONS = get_automation_operations()
TRACE_WINDOWS = {
    "1 min": 60,
    "5 min": 5 * 60,
    "1 hour": 60 * 60,
    "6 hours": 6 * 60 * 60,
    "24 hours": 24 * 60 * 60,
}

@st.cache_resource(on_release=lambda svc: svc.shutdown())
def get_serial_service(port: str, baudrate: int, use_mock: bool) -> SerialServiceLike:
    if use_mock:
        responder = F70Responder(
            system_on=False,
            temperatures=(45.0, 28.0, 26.5, 25.0),
            pressures=(1.15, 0.92),
            version="FAKE-DASH-1.0",
            elapsed_hours=123.4,
        )
        return FakeSerialService(responder=responder, port="MOCK", baudrate=baudrate)
    return SerialService.create(port, baudrate, timeout=1.0, default_timeout=10.0)


@st.cache_resource
def get_wlx_runtime(use_mock: bool) -> WLXRuntime:
    if use_mock:
        samples: dict[tuple[int, int], list[float | None]] = {
            (1, 0): [5.42, 5.36, 5.28, 5.18, 5.11, 5.07, 5.14, 5.31, 5.48, 5.22, 5.09, 5.05],
            (1, 1): [0.18, 0.20, 0.21, 0.24, 0.25, 0.27, 0.29, 0.30, 0.31, 0.29, 0.27, 0.26],
        }
        runtime = WLXRuntime.create(
            filepath="mock_setup.xcf",
            app_factory=lambda: FakeWaveLoggerApp(
                document=FakeWaveLoggerDocument(samples_by_channel=samples),
            ),
            poll_interval=0.5,
            channels=WAVELOGGER_CHANNELS,
        )
        runtime.runner.daemon = True
        return runtime

    setup_file = local_resources.get_path("sequential_capture.xcf")
    runtime = WLXRuntime.create(filepath=setup_file, channels=WAVELOGGER_CHANNELS)
    runtime.runner.daemon = True
    return runtime


def main() -> None:
    st.set_page_config(page_title="F70 Automation Dashboard", layout="wide")
    st.title("F70 Automation Dashboard")
    load_dotenv_file()

    st.session_state.setdefault(
        "dashboard_state",
        DashboardState(),
    )
    st.session_state.setdefault(
        "automation_settings",
        AutomationSettings(
            channels=WAVELOGGER_CHANNELS,
            operation_name=AUTOMATION_OPERATIONS[0].name,
        ),
    )
    st.session_state.setdefault("notification_settings", NotificationSettings())
    st.session_state.setdefault("monitor_runner", None)
    st.session_state.setdefault("periodic_runner", None)
    st.session_state.setdefault("last_mode", None)
    st.session_state.setdefault("settings_bootstrapped", False)
    st.session_state.setdefault("trace_window_label", "5 min")
    if "log_subscriber" not in st.session_state:
        _log_sub = StreamlitConsoleSubscriber(max_lines=200)
        get_app_logger().subscribe(_log_sub, min_level=LogLevel.INFO)
        st.session_state["log_subscriber"] = _log_sub
    state = cast(DashboardState, st.session_state.dashboard_state)
    settings = cast(AutomationSettings, st.session_state.automation_settings)
    notification_settings = cast(NotificationSettings, st.session_state.notification_settings)
    monitor_runner = cast(ThreadedMonitorRunner | None, st.session_state.monitor_runner)
    periodic_runner = cast(PeriodicNotificationRunner | None, st.session_state.periodic_runner)
    monitor_snapshot = get_monitor_snapshot(monitor_runner)
    if periodic_runner is not None and not monitor_snapshot.is_running:
        stop_periodic_notification_runner(periodic_runner)
        st.session_state.periodic_runner = None
        periodic_runner = None
    if periodic_runner is not None and not periodic_runner.is_alive():
        st.session_state.periodic_runner = None
        periodic_runner = None

    if not cast(bool, st.session_state.settings_bootstrapped):
        try:
            loaded_settings, loaded_notification_settings = load_dashboard_settings(
                channels=WAVELOGGER_CHANNELS,
                default_operation_name=AUTOMATION_OPERATIONS[0].name,
            )
            st.session_state.automation_settings = loaded_settings
            st.session_state.notification_settings = loaded_notification_settings
            settings = loaded_settings
            notification_settings = loaded_notification_settings
        except Exception as exc:
            state.last_error = str(exc)
        st.session_state.settings_bootstrapped = True

    tab_settings, tab_dashboard, tab_f70_command = st.tabs(["⚙️ Settings", "📊 Dashboard", "⌨️ F70 Command"])

    with tab_settings:
        with st.container(border=True):
            col_mode1, col_mode2 = st.columns((1, 3))
            with col_mode1:
                use_mock = st.toggle("Use Mock Devices", value=True)
            with col_mode2:
                st.caption("Mock mode uses in-process fake F70 and WaveLogger devices.")

        with st.container(border=True):
            st.subheader("Settings File")
            st.caption(f"Path: {DEFAULT_SETTINGS_PATH}")
            c_io1, c_io2 = st.columns(2)
            with c_io1:
                if st.button("Load Settings", width="stretch", disabled=monitor_snapshot.is_running):
                    try:
                        loaded_settings, loaded_notification_settings = load_dashboard_settings(
                            channels=WAVELOGGER_CHANNELS,
                            default_operation_name=AUTOMATION_OPERATIONS[0].name,
                        )
                        st.session_state.automation_settings = loaded_settings
                        st.session_state.notification_settings = loaded_notification_settings
                        st.session_state.settings_bootstrapped = True
                        get_app_logger().info(f"Settings loaded from {DEFAULT_SETTINGS_PATH}")
                        st.rerun()
                    except Exception as exc:
                        state.last_error = str(exc)
            with c_io2:
                if st.button("Save Settings", width="stretch", disabled=monitor_snapshot.is_running):
                    try:
                        save_dashboard_settings(
                            path=DEFAULT_SETTINGS_PATH,
                            settings=settings,
                            notification_settings=notification_settings,
                        )
                        get_app_logger().info(f"Settings saved to {DEFAULT_SETTINGS_PATH}")
                    except Exception as exc:
                        state.last_error = f"Settings save failed: {exc}"

        port, baudrate, op = render_settings_panel(
            use_mock=use_mock,
            settings=settings,
            notification_settings=notification_settings,
            automation_operations=AUTOMATION_OPERATIONS,
            wavelogger_channels=WAVELOGGER_CHANNELS,
            monitor_running=monitor_snapshot.is_running,
        )

    selected_channel = settings.selected_channel

    if st.session_state.last_mode is None:
        st.session_state.last_mode = use_mock
    elif st.session_state.last_mode != use_mock:
        action_mode_changed(
            state=state,
            resolve_stale_service=lambda: get_serial_service("MOCK" if st.session_state.last_mode else "COM3", 9600, st.session_state.last_mode),
            clear_service_cache=get_serial_service.clear,
            resolve_stale_runtime=lambda: get_wlx_runtime(st.session_state.last_mode),
            clear_runtime_cache=get_wlx_runtime.clear,
            monitor_runner=monitor_runner,
            periodic_runner=periodic_runner,
        )
        st.session_state.monitor_runner = None
        st.session_state.periodic_runner = None
        st.session_state.last_mode = use_mock

    try:
        service = get_serial_service(port, int(baudrate), use_mock)
    except Exception:
        service = None
    try:
        runtime = get_wlx_runtime(use_mock)
    except Exception:
        runtime = None

    state.f70_connected = bool(service and service.is_alive and not service.closed)
    state.wave_running = bool(runtime and runtime.runner.is_alive())
    monitor_snapshot = get_monitor_snapshot(monitor_runner)
    ready_for_automation, ready_reason = automation_ready(state)
    notification_dispatcher = None
    notification_message_factory = None
    periodic_notification_dispatcher = None
    periodic_notification_message_factory = None
    try:
        notification_dispatcher = build_notification_dispatcher(
            enabled=settings.notification_enabled,
            settings=notification_settings,
        )
        if notification_dispatcher is not None:
            notification_message_factory = build_trigger_message_factory(
                settings,
                "Mock" if use_mock else "Hardware",
            )
        periodic_notification_dispatcher = build_notification_dispatcher(
            enabled=notification_settings.slack_bot.periodic_message_enabled,
            settings=notification_settings,
            include_mentions=False,
        )
        if periodic_notification_dispatcher is not None and runtime is not None:
            periodic_notification_message_factory = build_periodic_message_factory(
                runtime,
                "Mock" if use_mock else "Hardware",
            )
    except Exception as exc:
        state.last_error = f"Notification setup failed: {exc}"

    with tab_dashboard:
        top_col1, top_col2, top_col3 = st.columns(3)

        with top_col1:
            with st.container(border=True):
                st.subheader("F70 Serial")
                st.metric("Connection", "Connected" if state.f70_connected else "Disconnected")
                if st.button("Reconnect", width='stretch', disabled=monitor_snapshot.is_running):
                    reconnect_f70(
                        dashboard_state=state,
                        resolve_service=lambda: get_serial_service(port, int(baudrate), use_mock),
                        clear_service_cache=get_serial_service.clear,
                        monitor_runner=monitor_runner,
                    )
                    st.session_state.monitor_runner = None
                    st.rerun()
                st.caption(f"Port: {port}")
                st.caption(f"Baudrate: {int(baudrate)}")

        with top_col2:
            with st.container(border=True):
                st.subheader("WaveLogger")
                st.metric("Acquisition", "Running" if state.wave_running else "Stopped")
                wave_action_label = "Stop Acquire" if state.wave_running else "Start Acquire"
                if st.button(wave_action_label, width='stretch'):
                    action_toggle_wave(
                        state=state,
                        settings=settings,
                        resolve_runtime=lambda: get_wlx_runtime(use_mock),
                        clear_runtime_cache=get_wlx_runtime.clear,
                        monitor_runner=monitor_runner,
                        periodic_runner=periodic_runner,
                    )
                    st.session_state.monitor_runner = None
                    st.session_state.periodic_runner = None
                    st.rerun()
                latest_value = None
                if runtime and runtime.runner.is_alive():
                    latest_value = runtime.store.get_current_physical(selected_channel)
                st.metric(
                    f"Latest {selected_channel.label}",
                    "N/A" if latest_value is None else f"{latest_value:.6g} {selected_channel.unit}",
                )

        with top_col3:
            with st.container(border=True):
                st.subheader("Automation")
                st.metric("State", "ON" if monitor_snapshot.is_running else "OFF")
                automation_label = "Automation OFF" if monitor_snapshot.is_running else "Automation ON"
                if st.button(
                    automation_label,
                    width='stretch',
                    disabled=(not monitor_snapshot.is_running) and (not ready_for_automation),
                ):
                    next_monitor_runner, next_periodic_runner = action_toggle_automation(
                        state=state,
                        monitor_runner=monitor_runner,
                        periodic_runner=periodic_runner,
                        service=service,
                        runtime=runtime,
                        settings=settings,
                        operation=op,
                        notification_dispatcher=notification_dispatcher,
                        notification_message_factory=notification_message_factory,
                        notification_failure_policy=notification_settings.failure_policy,
                        periodic_notification_dispatcher=periodic_notification_dispatcher,
                        periodic_notification_message_factory=periodic_notification_message_factory,
                        periodic_notification_interval_min=notification_settings.slack_bot.periodic_message_interval_min,
                    )
                    st.session_state.monitor_runner = next_monitor_runner
                    st.session_state.periodic_runner = next_periodic_runner
                    st.rerun()
                st.caption(ready_reason or "Automation can be armed.")
                st.caption(f"Input: {selected_channel.label}")
                st.caption(f"Threshold: {settings.threshold:.6g} {selected_channel.unit}")
                st.caption(f"Judge: {settings.required_sample_count} samples")
                st.caption(f"Operation: {op.name}")
                st.caption(
                    "Notification: "
                    + (
                        "disabled"
                        if not settings.notification_enabled
                        else f"enabled ({notification_settings.failure_policy})"
                    )
                )
                st.caption(
                    "Periodic Slack: "
                    + (
                        "disabled"
                        if not notification_settings.slack_bot.periodic_message_enabled
                        else f"every {notification_settings.slack_bot.periodic_message_interval_min} min"
                    )
                )

        @st.fragment(run_every=1)
        def live_view() -> None:
            current_service: SerialServiceLike | None
            current_runtime: WLXRuntime | None
            try:
                current_service = get_serial_service(port, int(baudrate), use_mock)
            except Exception:
                current_service = None
            try:
                current_runtime = get_wlx_runtime(use_mock)
            except Exception:
                current_runtime = None

            state.f70_connected = bool(current_service and current_service.is_alive and not current_service.closed)
            state.wave_running = bool(current_runtime and current_runtime.runner.is_alive())
            live_monitor_runner = cast(ThreadedMonitorRunner | None, st.session_state.monitor_runner)
            live_periodic_runner = cast(PeriodicNotificationRunner | None, st.session_state.periodic_runner)
            live_snapshot = get_monitor_snapshot(live_monitor_runner)
            if live_periodic_runner is not None and not live_snapshot.is_running:
                stop_periodic_notification_runner(live_periodic_runner)
                st.session_state.periodic_runner = None
            selected_live_channel = settings.selected_channel
            latest_live_value = None
            if current_runtime and current_runtime.runner.is_alive():
                latest_live_value = current_runtime.store.get_current_physical(selected_live_channel)

            with st.container(border=True):
                st.subheader("Live Status")
                st.caption(f"Mode: {'Mock' if use_mock else 'Hardware'}")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("F70", "Connected" if state.f70_connected else "Disconnected")
                c2.metric("WaveLogger", "Running" if state.wave_running else "Stopped")
                c3.metric("Automation", "RUNNING" if live_snapshot.is_running else "STOPPED")
                c4.metric("Last Triggered", live_snapshot.last_trigger_time.strftime("%Y-%m-%d %H:%M:%S") if live_snapshot.last_trigger_time else "N/A")
                c5, c6 = st.columns(2)
                c5.metric(
                    f"Latest {selected_live_channel.label}",
                    "N/A" if latest_live_value is None else f"{latest_live_value:.6g} {selected_live_channel.unit}",
                )
                c6.metric("Last Command", format_trigger_result(live_snapshot.last_trigger_result))
                if state.blocked_reason:
                    st.warning(f"Automation blocked: {state.blocked_reason}")
                monitor_error = format_monitor_error(live_snapshot.last_error)
                if monitor_error or state.last_error:
                    st.error(f"Automation error: {monitor_error or state.last_error}")

            bottom_left, bottom_right = st.columns((1, 2))

            with bottom_left:
                with st.container(border=True):
                    st.subheader("F70 Status")
                    try:
                        if current_service is None:
                            raise RuntimeError("F70 service is unavailable.")
                        status = read_f70_status(current_service)
                        s1, s2 = st.columns(2)
                        s1.metric("System Power", "ON" if status.system_on else "OFF")
                        s2.metric("State", status.state_number.name)
                        s3, s4 = st.columns(2)
                        s3.metric("Config", status.config_mode.name)
                        alarms = get_active_alarm_names(status)
                        s4.metric("Alarm Count", len(alarms))
                        st.write("Active alarms:", ", ".join(alarms) if alarms else "None")
                    except Exception as exc:
                        st.warning(f"F70 status read failed: {exc}")

            with bottom_right:
                with st.container(border=True):
                    st.subheader("WaveLogger Trace")
                    trace_window_label = st.selectbox(
                        "Trace Window",
                        options=list(TRACE_WINDOWS.keys()),
                        index=list(TRACE_WINDOWS.keys()).index(st.session_state.trace_window_label),
                    )
                    st.session_state.trace_window_label = trace_window_label
                    sample_window = TRACE_WINDOWS[trace_window_label]
                    if current_runtime and current_runtime.runner.is_alive():
                        latest_cols = st.columns(len(WAVELOGGER_CHANNELS))
                        for col, channel in zip(latest_cols, WAVELOGGER_CHANNELS):
                            value = current_runtime.store.get_current_physical(channel)
                            col.metric(channel.label, "N/A" if value is None else f"{value:.3E} {channel.unit}")
                        chart_cols = st.columns(len(WAVELOGGER_CHANNELS))
                        for col, channel in zip(chart_cols, WAVELOGGER_CHANNELS):
                            with col:
                                history = current_runtime.store.get_physical_history(channel)[-sample_window:]
                                st.caption(f"{channel.label} [{channel.unit}]")
                                if history:
                                    st.line_chart(
                                        pd.DataFrame({channel.label: history}),
                                        width='stretch',
                                    )
                                else:
                                    st.info(f"{channel.label} has no samples yet.")
                    else:
                        st.info("WaveLogger acquisition is stopped.")

            with st.container(border=True):
                st.subheader("Log Console")
                log_sub = cast(StreamlitConsoleSubscriber, st.session_state.get("log_subscriber"))
                if log_sub is not None:
                    log_sub.render_to_streamlit(clear_button_key="automation_log_console_clear")

        live_view()

    with tab_f70_command:
        render_f70_command_console_component(
            service=service,
            mode_label="Mock" if use_mock else "Hardware",
            port=port,
            baudrate=int(baudrate),
            key_prefix="f70_console_dashboard",
            disable_control_commands=monitor_snapshot.is_running,
        )


if __name__ == "__main__":
    main()
