import threading
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd
import streamlit as st

import f70_automate.resources as local_resources
from f70_automate.f70_serial import f70_operation as f70_op
from f70_automate.f70_serial.f70_operation import F70Operation
from f70_automate.serial_service import SerialService
from f70_automate.test.mock.fake_serial_f70 import F70Responder
from f70_automate.test.mock.fake_serial_service import FakeSerialService
from f70_automate.test.mock.fake_wavelogger import FakeWaveLoggerApp, FakeWaveLoggerDocument
from f70_automate.wavelogger.channel_config import ChannelConfig, TransformKind
from f70_automate.wavelogger.wlx_thread import WLXDataLogger

WAVELOGGER_CHANNELS = (
    ChannelConfig(
        "ch_pressure",
        "Pressure",
        1,
        0,
        transform=TransformKind.LOG10_EXP,
        scale=1.667,
        offset=-9.333,
        unit="Pa",
    ),
    ChannelConfig("ch_temperature", "Temperature", 1, 1, scale=25.0, offset=273.15, unit="K"),
    ChannelConfig("ch_flow", "Flow", 1, 2, scale=10.0, offset=0.0, unit="L/min"),
)


@dataclass
class AutomationState:
    f70_connected: bool = False
    wave_running: bool = False
    automation_enabled: bool = False
    selected_channel_key: str = WAVELOGGER_CHANNELS[0].key
    last_physical_value: float | None = None
    last_trigger_time: float | None = None
    last_error: str | None = None
    trigger_count: int = 0
    last_command: str | None = None
    blocked_reason: str | None = None


def get_selected_channel() -> ChannelConfig:
    return next(channel for channel in WAVELOGGER_CHANNELS if channel.key == st.session_state.automation_state.selected_channel_key)

@st.cache_resource(on_release=lambda svc: svc.shutdown())
def get_serial_service(port: str, baudrate: int, use_mock: bool) -> SerialService | FakeSerialService:
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
def get_wlx_logger(use_mock: bool) -> WLXDataLogger:
    if use_mock:
        samples = {
            (1, 0): [0.42, 0.36, 0.28, 0.18, 0.11, 0.07, 0.14, 0.31, 0.48, 0.22, 0.09, 0.05],
            (1, 1): [0.18, 0.20, 0.21, 0.24, 0.25, 0.27, 0.29, 0.30, 0.31, 0.29, 0.27, 0.26],
            (1, 2): [0.08, 0.07, 0.10, 0.11, 0.14, 0.18, 0.16, 0.13, 0.09, 0.07, 0.06, 0.05],
        }
        logger = WLXDataLogger(
            filepath="mock_setup.xcf",
            app_factory=lambda: FakeWaveLoggerApp(
                document=FakeWaveLoggerDocument(samples_by_channel=samples),
            ),
            poll_interval=0.5,
            channels=WAVELOGGER_CHANNELS,
        )
        logger.daemon = True
        return logger

    setup_file = local_resources.get_path("sequential_capture.xcf")
    logger = WLXDataLogger(setup_file, channels=WAVELOGGER_CHANNELS)
    logger.daemon = True
    return logger


def send_f70_operation(service: SerialService, operation: F70Operation) -> str:
    service.call_checked(operation)
    return operation.name


def read_f70_status(service: SerialService | FakeSerialService):
    return service.call(f70_op.read_status)


def monitor_loop(
    state: AutomationState,
    logger: WLXDataLogger,
    service: SerialService | FakeSerialService,
    channel: ChannelConfig,
    threshold: float,
    operation: F70Operation,
    cooldown_sec: float,
    poll_sec: float,
) -> None:
    while state.automation_enabled:
        try:
            if not logger.is_alive():
                state.blocked_reason = "WaveLogger acquisition is stopped."
                state.automation_enabled = False
                break

            physical_value = logger.get_current_physical(channel)
            state.last_physical_value = physical_value
            if physical_value is None:
                time.sleep(poll_sec)
                continue

            now = time.time()
            in_cooldown = (
                state.last_trigger_time is not None
                and now - state.last_trigger_time < cooldown_sec
            )
            if (physical_value < threshold) and (not in_cooldown):
                sent = send_f70_operation(service, operation)
                state.last_trigger_time = now
                state.trigger_count += 1
                state.last_command = sent
                state.last_error = None
                state.blocked_reason = None
        except Exception as exc:
            state.last_error = str(exc)
            state.blocked_reason = str(exc)
            state.automation_enabled = False
            break
        time.sleep(poll_sec)


def stop_monitoring(state: AutomationState) -> None:
    state.automation_enabled = False


def start_monitoring(
    logger: WLXDataLogger,
    state: AutomationState,
    service: SerialService | FakeSerialService,
    channel: ChannelConfig,
    threshold: float,
    operation: F70Operation,
    cooldown_sec: float,
    poll_sec: float,
) -> threading.Thread | None:
    if state.automation_enabled:
        return None

    state.automation_enabled = True
    state.blocked_reason = None
    monitor_thread = threading.Thread(
        target=monitor_loop,
        args=(state, logger, service, channel, threshold, operation, cooldown_sec, poll_sec),
        daemon=True,
    )
    monitor_thread.start()
    return monitor_thread


def stop_wave_logger(logger: WLXDataLogger, state: AutomationState) -> None:
    stop_monitoring(state)
    if logger.is_alive():
        logger.stop()
        logger.join(timeout=1.0)


def reset_serial_service(port: str, baudrate: int, use_mock: bool) -> None:
    try:
        service = get_serial_service(port, baudrate, use_mock)
        service.shutdown()
    except Exception:
        pass
    get_serial_service.clear()


def reset_wave_logger(use_mock: bool, state: AutomationState) -> None:
    try:
        logger = get_wlx_logger(use_mock)
        stop_wave_logger(logger, state)
    except Exception:
        pass
    get_wlx_logger.clear()


def reconnect_f70(state: AutomationState, port: str, baudrate: int, use_mock: bool) -> SerialService | FakeSerialService | None:
    stop_monitoring(state)
    reset_serial_service(port, baudrate, use_mock)
    try:
        service = get_serial_service(port, baudrate, use_mock)
        read_f70_status(service)
        state.f70_connected = True
        state.last_error = None
        state.blocked_reason = None
        return service
    except Exception as exc:
        state.f70_connected = False
        state.last_error = f"F70 reconnect failed: {exc}"
        state.blocked_reason = "F70 is disconnected."
        return None


def start_wave_acquisition(state: AutomationState, use_mock: bool) -> WLXDataLogger | None:
    reset_wave_logger(use_mock, state)
    try:
        logger = get_wlx_logger(use_mock)
        logger.start()
        logger.wait_until_awake()
        state.wave_running = True
        state.last_physical_value = logger.get_current_physical(get_selected_channel())
        state.last_error = None
        state.blocked_reason = None
        return logger
    except Exception as exc:
        state.wave_running = False
        state.last_error = f"WaveLogger start failed: {exc}"
        state.blocked_reason = "WaveLogger acquisition failed."
        return None


def stop_wave_acquisition(state: AutomationState, use_mock: bool) -> None:
    reset_wave_logger(use_mock, state)
    state.wave_running = False


def update_runtime_state(
    state: AutomationState,
    service: SerialService | FakeSerialService | None,
    logger: WLXDataLogger | None,
) -> None:
    state.f70_connected = bool(service and service.is_alive and not service.closed)
    state.wave_running = bool(logger and logger.is_alive())
    if not state.f70_connected and state.automation_enabled:
        state.automation_enabled = False
        state.blocked_reason = "F70 is disconnected."
    if not state.wave_running and state.automation_enabled:
        state.automation_enabled = False
        state.blocked_reason = "WaveLogger acquisition is stopped."


def automation_ready(state: AutomationState) -> tuple[bool, str | None]:
    if not state.f70_connected:
        return False, "Reconnect F70 first."
    if not state.wave_running:
        return False, "Start WaveLogger acquisition first."
    return True, None


def main() -> None:
    st.set_page_config(page_title="F70 Automation Dashboard", layout="wide")
    st.title("F70 Automation Dashboard")

    st.session_state.setdefault("automation_state", AutomationState())
    st.session_state.setdefault("monitor_thread", None)
    st.session_state.setdefault("last_mode", None)
    state: AutomationState = st.session_state.automation_state

    with st.container(border=True):
        col_mode1, col_mode2 = st.columns((1, 3))
        with col_mode1:
            use_mock = st.toggle("Use Mock Devices", value=True)
        with col_mode2:
            st.caption("Mock mode uses in-process fake F70 and WaveLogger devices.")

    if st.session_state.last_mode is None:
        st.session_state.last_mode = use_mock
    elif st.session_state.last_mode != use_mock:
        stop_monitoring(state)
        reset_serial_service("MOCK" if st.session_state.last_mode else "COM3", 9600, st.session_state.last_mode)
        reset_wave_logger(st.session_state.last_mode, state)
        state.f70_connected = False
        state.wave_running = False
        st.session_state.monitor_thread = None
        st.session_state.last_mode = use_mock

    with st.container(border=True):
        st.subheader("Automation Settings")
        col_cfg1, col_cfg2, col_cfg3, col_cfg4, col_cfg5 = st.columns(5)
        with col_cfg1:
            default_port = "MOCK" if use_mock else "COM3"
            port = st.text_input("F70 COM Port", value=default_port, disabled=use_mock)
        with col_cfg2:
            baudrate = st.number_input("Baudrate", min_value=1200, max_value=115200, value=9600, step=1200)
        with col_cfg3:
            threshold = st.number_input("Trigger Threshold", value=0.1, step=0.01, format="%.3f")
        with col_cfg4:
            cooldown_sec = st.number_input("Cooldown [sec]", min_value=0.0, value=3.0, step=0.5)
        with col_cfg5:
            selected_channel = st.selectbox(
                "Automation Input",
                options=WAVELOGGER_CHANNELS,
                index=next(i for i, channel in enumerate(WAVELOGGER_CHANNELS) if channel.key == state.selected_channel_key),
                format_func=lambda channel: channel.label,
            )
            state.selected_channel_key = selected_channel.key

        op = st.selectbox(
            "Command when physical value < threshold",
            options=[
                f70_op.power_on,
                f70_op.power_off,
                f70_op.coldhead_run,
                f70_op.coldhead_pause,
                f70_op.reset,
            ],
            format_func=lambda x: x.name,
        )
        poll_sec = st.slider("Polling interval [sec]", min_value=0.2, max_value=2.0, value=1.0, step=0.1)
        st.caption(f"Threshold unit: {selected_channel.unit}")

    try:
        service = get_serial_service(port, int(baudrate), use_mock)
    except Exception:
        service = None
    try:
        logger = get_wlx_logger(use_mock)
    except Exception:
        logger = None

    update_runtime_state(state, service, logger)
    ready_for_automation, ready_reason = automation_ready(state)

    top_col1, top_col2, top_col3 = st.columns(3)

    with top_col1:
        with st.container(border=True):
            st.subheader("F70 Serial")
            st.metric("Connection", "Connected" if state.f70_connected else "Disconnected")
            if st.button("Reconnect", use_container_width=True, disabled=state.automation_enabled):
                service = reconnect_f70(state, port, int(baudrate), use_mock)
                if service is not None:
                    st.rerun()
            st.caption(f"Port: {port}")
            st.caption(f"Baudrate: {int(baudrate)}")

    with top_col2:
        with st.container(border=True):
            st.subheader("WaveLogger")
            st.metric("Acquisition", "Running" if state.wave_running else "Stopped")
            wave_action_label = "Stop Acquire" if state.wave_running else "Start Acquire"
            if st.button(wave_action_label, use_container_width=True):
                if state.wave_running:
                    stop_wave_acquisition(state, use_mock)
                    logger = None
                    st.rerun()
                else:
                    logger = start_wave_acquisition(state, use_mock)
                    if logger is not None:
                        st.rerun()
            latest_value = state.last_physical_value
            st.metric(
                f"Latest {selected_channel.label}",
                "N/A" if latest_value is None else f"{latest_value:.6g} {selected_channel.unit}",
            )

    with top_col3:
        with st.container(border=True):
            st.subheader("Automation")
            st.metric("State", "ON" if state.automation_enabled else "OFF")
            automation_label = "Automation OFF" if state.automation_enabled else "Automation ON"
            if st.button(
                automation_label,
                use_container_width=True,
                disabled=(not state.automation_enabled) and (not ready_for_automation),
            ):
                if state.automation_enabled:
                    stop_monitoring(state)
                    st.session_state.monitor_thread = None
                    st.rerun()
                else:
                    monitor_thread = start_monitoring(
                        logger=logger,
                        state=state,
                        service=service,
                        channel=selected_channel,
                        threshold=float(threshold),
                        operation=op,
                        cooldown_sec=float(cooldown_sec),
                        poll_sec=float(poll_sec),
                    )
                    st.session_state.monitor_thread = monitor_thread
                    if monitor_thread is not None:
                        st.rerun()
            st.caption(ready_reason or "Automation can be armed.")
            st.caption(f"Input: {selected_channel.label}")
            st.caption(f"Operation: {op.name}")

    @st.fragment(run_every=1)
    def live_view() -> None:
        current_service: Any
        current_logger: Any
        try:
            current_service = get_serial_service(port, int(baudrate), use_mock)
        except Exception:
            current_service = None
        try:
            current_logger = get_wlx_logger(use_mock)
        except Exception:
            current_logger = None

        update_runtime_state(state, current_service, current_logger)
        selected_live_channel = next(channel for channel in WAVELOGGER_CHANNELS if channel.key == state.selected_channel_key)
        if current_logger and current_logger.is_alive():
            state.last_physical_value = current_logger.get_current_physical(selected_live_channel)

        with st.container(border=True):
            st.subheader("Live Status")
            st.caption(f"Mode: {'Mock' if use_mock else 'Hardware'}")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("F70", "Connected" if state.f70_connected else "Disconnected")
            c2.metric("WaveLogger", "Running" if state.wave_running else "Stopped")
            c3.metric("Automation", "RUNNING" if state.automation_enabled else "STOPPED")
            c4.metric("Trigger Count", state.trigger_count)
            c5, c6 = st.columns(2)
            c5.metric(
                f"Latest {selected_live_channel.label}",
                "N/A" if state.last_physical_value is None else f"{state.last_physical_value:.6g} {selected_live_channel.unit}",
            )
            c6.metric("Last Command", state.last_command or "N/A")
            if state.blocked_reason:
                st.warning(f"Automation blocked: {state.blocked_reason}")
            if state.last_error:
                st.error(f"Automation error: {state.last_error}")

        bottom_left, bottom_right = st.columns((1, 2))

        with bottom_left:
            with st.container(border=True):
                st.subheader("F70 Status")
                try:
                    status = read_f70_status(current_service)
                    s1, s2 = st.columns(2)
                    s1.metric("System Power", "ON" if status.system_on else "OFF")
                    s2.metric("State", status.state_number.name)
                    s3, s4 = st.columns(2)
                    s3.metric("Config", status.config_mode.name)
                    s4.metric("Alarm Count", sum(
                        [
                            status.pressure_alarm,
                            status.oil_alarm,
                            status.water_flow_alarm,
                            status.water_temp_alarm,
                            status.helium_temp_alarm,
                            status.phase_alarm,
                            status.motor_temp_alarm,
                        ]
                    ))

                    alarms = []
                    if status.pressure_alarm:
                        alarms.append("Pressure")
                    if status.oil_alarm:
                        alarms.append("Oil")
                    if status.water_flow_alarm:
                        alarms.append("Water Flow")
                    if status.water_temp_alarm:
                        alarms.append("Water Temp")
                    if status.helium_temp_alarm:
                        alarms.append("Helium Temp")
                    if status.phase_alarm:
                        alarms.append("Phase/Fuse")
                    if status.motor_temp_alarm:
                        alarms.append("Motor Temp")
                    st.write("Active alarms:", ", ".join(alarms) if alarms else "None")
                except Exception as exc:
                    st.warning(f"F70 status read failed: {exc}")

        with bottom_right:
            with st.container(border=True):
                st.subheader("WaveLogger Trace")
                if current_logger and current_logger.is_alive():
                    latest_cols = st.columns(len(WAVELOGGER_CHANNELS))
                    for col, channel in zip(latest_cols, WAVELOGGER_CHANNELS):
                        value = current_logger.get_current_physical(channel)
                        col.metric(channel.label, "N/A" if value is None else f"{value:.6g} {channel.unit}")

                    chart_data = {
                        channel.label: current_logger.get_physical_history(channel)
                        for channel in WAVELOGGER_CHANNELS
                    }
                    st.line_chart(pd.DataFrame(chart_data), use_container_width=True)
                else:
                    st.info("WaveLogger acquisition is stopped.")

    live_view()


if __name__ == "__main__":
    main()
