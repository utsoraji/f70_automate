import threading
import time
from dataclasses import dataclass

import streamlit as st

import f70_automate.resources as local_resources
from f70_automate.f70_serial import f70_operation as f70_op
from f70_automate.f70_serial.f70_operation import F70Operation
from f70_automate.serial_service import SerialService
from f70_automate.wavelogger.wlx_thread import WLXDataLogger


@dataclass
class AutomationState:
    active: bool = False
    last_voltage: float | None = None
    last_trigger_time: float | None = None
    last_error: str | None = None
    trigger_count: int = 0
    last_command: str | None = None


@st.cache_resource(on_release=lambda svc: svc.shutdown())
def get_serial_service(port: str, baudrate: int) -> SerialService:
    return SerialService.create(port, baudrate, timeout=1.0, default_timeout=10.0)


@st.cache_resource
def get_wlx_logger() -> WLXDataLogger:
    setup_file = local_resources.get_path("sequential_capture.xcf")
    logger = WLXDataLogger(setup_file)
    logger.daemon = True
    return logger


def send_f70_operation(service: SerialService, operation: F70Operation) -> str:
    service.call_checked(operation)
    return operation.name


def read_f70_status(service: SerialService):
    return service.call(f70_op.read_status)


def monitor_loop(
    state: AutomationState,
    logger: WLXDataLogger,
    service: SerialService,
    threshold: float,
    operation: F70Operation,
    cooldown_sec: float,
    poll_sec: float,
) -> None:
    while state.active:
        try:
            voltage = logger.current_data
            state.last_voltage = voltage
            if voltage is None:
                time.sleep(poll_sec)
                continue

            now = time.time()
            in_cooldown = (
                state.last_trigger_time is not None
                and now - state.last_trigger_time < cooldown_sec
            )
            if (voltage < threshold) and (not in_cooldown):
                sent = send_f70_operation(service, operation)
                state.last_trigger_time = now
                state.trigger_count += 1
                state.last_command = sent
                state.last_error = None
        except Exception as exc:
            state.last_error = str(exc)
        time.sleep(poll_sec)


def start_workers(
    logger: WLXDataLogger,
    state: AutomationState,
    service: SerialService,
    threshold: float,
    operation: F70Operation,
    cooldown_sec: float,
    poll_sec: float,
) -> None:
    if not logger.is_alive():
        logger.start()
        logger.wait_until_awake()

    if state.active:
        return

    state.active = True
    t = threading.Thread(
        target=monitor_loop,
        args=(state, logger, service, threshold, operation, cooldown_sec, poll_sec),
        daemon=True,
    )
    t.start()


def stop_workers(logger: WLXDataLogger, state: AutomationState) -> None:
    state.active = False
    if logger.is_alive():
        logger.stop()


def main() -> None:
    st.set_page_config(page_title="F70 Automation Dashboard", layout="wide")
    st.title("F70 Automation Dashboard")

    st.session_state.setdefault("automation_state", AutomationState())
    state: AutomationState = st.session_state.automation_state

    col_cfg1, col_cfg2, col_cfg3, col_cfg4 = st.columns(4)
    with col_cfg1:
        port = st.text_input("F70 COM Port", value="COM3")
    with col_cfg2:
        baudrate = st.number_input("Baudrate", min_value=1200, max_value=115200, value=9600, step=1200)
    with col_cfg3:
        threshold = st.number_input("Trigger Voltage", value=0.1, step=0.01, format="%.3f")
    with col_cfg4:
        cooldown_sec = st.number_input("Cooldown [sec]", min_value=0.0, value=3.0, step=0.5)

    op = st.selectbox(
        "Command when voltage < threshold",
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

    service = get_serial_service(port, int(baudrate))
    logger = get_wlx_logger()

    col_action1, col_action2 = st.columns(2)
    with col_action1:
        if st.button("Start Automation", use_container_width=True):
            start_workers(logger, state, service, float(threshold), op, float(cooldown_sec), float(poll_sec))
    with col_action2:
        if st.button("Stop Automation", use_container_width=True):
            stop_workers(logger, state)

    @st.fragment(run_every=1)
    def live_view() -> None:
        st.subheader("Live View")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Automation", "RUNNING" if state.active else "STOPPED")
        c2.metric("Latest Voltage", "N/A" if state.last_voltage is None else f"{state.last_voltage:.6g}")
        c3.metric("Trigger Count", state.trigger_count)
        c4.metric("Last Command", state.last_command or "N/A")

        st.subheader("F70 Status")
        try:
            status = read_f70_status(service)
            s1, s2, s3 = st.columns(3)
            s1.metric("System Power", "ON" if status.system_on else "OFF")
            s2.metric("State", status.state_number.name)
            s3.metric("Config", status.config_mode.name)

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

        st.subheader("WaveLogger Trace")
        if logger.is_alive() and logger.current_data is not None:
            st.line_chart(logger.data)
        else:
            st.info("WaveLogger is not running.")

        if state.last_error:
            st.error(f"Automation error: {state.last_error}")

    live_view()


if __name__ == "__main__":
    main()
