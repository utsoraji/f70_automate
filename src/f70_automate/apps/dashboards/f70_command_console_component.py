from __future__ import annotations

import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Concatenate, ParamSpec, Protocol, TypeVar, cast

import streamlit as st

from f70_automate._core.logging import FileLogSubscriber, LogLevel, get_app_logger
from f70_automate._core.serial.serial_async import SerialPortLike
from f70_automate._core.serial.serial_service import (
    CallableWithCanExecute,
    SerialServiceError,
    SerialServiceTimeoutError,
)
from f70_automate.apps.dashboards.logging_subscribers import StreamlitConsoleSubscriber
from f70_automate.domains.f70_serial import f70_operation as f70_op
from f70_automate.domains.f70_serial import f70_serial as f70

P = ParamSpec("P")
R = TypeVar("R", covariant=True)


class SerialServiceLike(Protocol):
    @property
    def is_alive(self) -> bool: ...

    @property
    def closed(self) -> bool: ...

    def call(self, fn: Callable[Concatenate[SerialPortLike, P], R], *a: P.args, **kw: P.kwargs) -> R: ...

    def call_checked(self, operation: CallableWithCanExecute[P, R]) -> R: ...


READ_COMMANDS: tuple[tuple[str, f70_op.F70Operation, int | None], ...] = (
    ("Read Status", f70_op.read_status, None),
    ("Read Version", f70_op.read_version, None),
    ("Read All Temperatures", f70_op.read_all_temperatures, None),
    ("Read Temperature", f70_op.read_temperature, 1),
    ("Read All Pressures", f70_op.read_all_pressures, None),
    ("Read Pressure", f70_op.read_pressure, 1),
)


def _k(prefix: str, name: str) -> str:
    return f"{prefix}_{name}"


def _safe_jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {str(k): _safe_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_jsonable(v) for v in value]
    if hasattr(value, "name"):
        return str(getattr(value, "name"))
    return str(value)


def _format_result(result: Any) -> tuple[str, Any]:
    if isinstance(result, f70.F70Frame):
        parsed = {
            "command": result.command.value,
            "data": list(result.data),
            "crc": result.crc.hex,
        }
        return str(result), parsed

    if isinstance(result, f70.F70StatusBits):
        parsed = {
            "hex": result.hex_str,
            "system_on": result.system_on,
            "config_mode": result.config_mode.name,
            "state_number": result.state_number.name,
            "solenoid_on": result.solenoid_on,
            "alarms": {
                "pressure": result.pressure_alarm,
                "oil": result.oil_alarm,
                "water_flow": result.water_flow_alarm,
                "water_temp": result.water_temp_alarm,
                "helium_temp": result.helium_temp_alarm,
                "phase": result.phase_alarm,
                "motor_temp": result.motor_temp_alarm,
            },
        }
        return str(result), parsed

    raw = str(result)
    return raw, _safe_jsonable(result)


def _append_history(prefix: str, entry: dict[str, Any]) -> None:
    history_key = _k(prefix, "command_history")
    history = cast(list[dict[str, Any]], st.session_state[history_key])
    history.insert(0, entry)
    st.session_state[history_key] = history[:100]


def _record_last_read_status(prefix: str, status: f70.F70StatusBits, *, at_time: str | None = None) -> None:
    _, parsed = _format_result(status)
    st.session_state[_k(prefix, "last_read_status")] = {
        "raw": str(status),
        "parsed": parsed,
        "timestamp": at_time or time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _refresh_status_after_control(prefix: str, service: SerialServiceLike, *, trigger_label: str) -> None:
    logger = get_app_logger()
    try:
        status = service.call(f70_op.read_status)
        _record_last_read_status(prefix, status)
        logger.info(
            "ReadStatus refreshed after control command.",
            source="F70Console",
            context={"trigger": trigger_label},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"ReadStatus refresh failed after {trigger_label}: {exc}",
            source="F70Console",
        )


def _run_command(
    *,
    prefix: str,
    service: SerialServiceLike,
    label: str,
    operation: f70_op.F70Operation,
    args: tuple[Any, ...] = (),
    checked: bool = False,
) -> None:
    start = time.perf_counter()
    logger = get_app_logger()

    try:
        if checked:
            result = service.call_checked(operation)
        else:
            result = service.call(operation, *args)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        raw, parsed = _format_result(result)

        st.session_state[_k(prefix, "last_result")] = {
            "ok": True,
            "label": label,
            "operation": operation.name,
            "args": list(args),
            "elapsed_ms": round(elapsed_ms, 2),
            "raw": raw,
            "parsed": parsed,
            "error": None,
        }
        _append_history(
            prefix,
            {
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "category": "control" if checked else "read",
                "command": label,
                "args": str(list(args)),
                "status": "success",
                "latency_ms": round(elapsed_ms, 2),
                "detail": raw,
            },
        )
        logger.info(
            f"F70 command success: {label}",
            source="F70Console",
            context={"operation": operation.name, "args": list(args), "latency_ms": round(elapsed_ms, 2)},
        )
        if operation is f70_op.read_status and isinstance(result, f70.F70StatusBits):
            _record_last_read_status(prefix, result)
        elif checked:
            _refresh_status_after_control(prefix, service, trigger_label=label)
    except (SerialServiceTimeoutError, TimeoutError) as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        message = f"Timeout: {exc}"
        st.session_state[_k(prefix, "last_result")] = {
            "ok": False,
            "label": label,
            "operation": operation.name,
            "args": list(args),
            "elapsed_ms": round(elapsed_ms, 2),
            "raw": "",
            "parsed": None,
            "error": message,
        }
        _append_history(
            prefix,
            {
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "category": "control" if checked else "read",
                "command": label,
                "args": str(list(args)),
                "status": "timeout",
                "latency_ms": round(elapsed_ms, 2),
                "detail": message,
            },
        )
        logger.error(message, source="F70Console", context={"operation": operation.name, "args": list(args)})
    except (SerialServiceError, RuntimeError, ValueError) as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        message = f"Error: {exc}"
        st.session_state[_k(prefix, "last_result")] = {
            "ok": False,
            "label": label,
            "operation": operation.name,
            "args": list(args),
            "elapsed_ms": round(elapsed_ms, 2),
            "raw": "",
            "parsed": None,
            "error": message,
        }
        _append_history(
            prefix,
            {
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "category": "control" if checked else "read",
                "command": label,
                "args": str(list(args)),
                "status": "error",
                "latency_ms": round(elapsed_ms, 2),
                "detail": message,
            },
        )
        logger.error(message, source="F70Console", context={"operation": operation.name, "args": list(args)})


def _resolve_selected_read_operation(label: str) -> tuple[f70_op.F70Operation, int | None]:
    for item_label, operation, default_sensor in READ_COMMANDS:
        if item_label == label:
            return operation, default_sensor
    raise ValueError(f"Unknown read command label: {label}")


@st.dialog("Confirm Control Command")
def _render_control_confirm_dialog(
    *,
    prefix: str,
    service: SerialServiceLike,
    label: str,
    operation: f70_op.F70Operation,
) -> None:
    st.write(f"Execute `{label}`?")
    st.warning("This command may change the F70 operating state.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Execute", type="primary", width="stretch", key=_k(prefix, f"confirm_exec_{operation.name}")):
            _run_command(prefix=prefix, service=service, label=label, operation=operation, checked=True)
            st.rerun()
    with c2:
        if st.button("Cancel", width="stretch", key=_k(prefix, f"confirm_cancel_{operation.name}")):
            st.rerun()


def _render_read_panel(prefix: str, service: SerialServiceLike | None) -> None:
    with st.container(border=True):
        st.subheader("Read Commands")
        selected_label = st.selectbox(
            "Select Read Command",
            [item[0] for item in READ_COMMANDS],
            key=_k(prefix, "read_select"),
        )
        operation, default_sensor = _resolve_selected_read_operation(selected_label)

        args: tuple[Any, ...] = ()
        if operation is f70_op.read_temperature:
            sensor_id = st.selectbox("Temperature Sensor", [1, 2, 3, 4], index=(default_sensor or 1) - 1, key=_k(prefix, "temp_sensor"))
            args = (sensor_id,)
        elif operation is f70_op.read_pressure:
            sensor_id = st.selectbox("Pressure Sensor", [1, 2], index=(default_sensor or 1) - 1, key=_k(prefix, "pressure_sensor"))
            args = (sensor_id,)

        send_disabled = service is None or not service.is_alive or service.closed
        if st.button("Send Read Command", width="stretch", disabled=send_disabled, key=_k(prefix, "send_read")):
            assert service is not None
            _run_command(prefix=prefix, service=service, label=selected_label, operation=operation, args=args, checked=False)


def _render_control_panel(prefix: str, service: SerialServiceLike | None, *, force_disabled: bool = False) -> None:
    with st.container(border=True):
        st.subheader("Control Commands")
        st.caption("Control commands are separated and require explicit acknowledgment.")
        acknowledged = st.checkbox(
            "I understand these commands can change F70 state.",
            key=_k(prefix, "control_ack"),
        )

        send_disabled = service is None or not service.is_alive or service.closed or (not acknowledged) or force_disabled
        if force_disabled:
            st.info("Control commands are disabled while automation is running.")
        c1, c2, c3 = st.columns(3)

        with c1:
            if st.button("Power ON", width="stretch", disabled=send_disabled, key=_k(prefix, "power_on")):
                assert service is not None
                _render_control_confirm_dialog(prefix=prefix, service=service, label="Power ON", operation=f70_op.power_on)
            if st.button("ColdHead RUN", width="stretch", disabled=send_disabled, key=_k(prefix, "coldhead_run")):
                assert service is not None
                _render_control_confirm_dialog(prefix=prefix, service=service, label="ColdHead RUN", operation=f70_op.coldhead_run)

        with c2:
            if st.button("Power OFF", width="stretch", disabled=send_disabled, key=_k(prefix, "power_off")):
                assert service is not None
                _render_control_confirm_dialog(prefix=prefix, service=service, label="Power OFF", operation=f70_op.power_off)
            if st.button("ColdHead PAUSE", width="stretch", disabled=send_disabled, key=_k(prefix, "coldhead_pause")):
                assert service is not None
                _render_control_confirm_dialog(prefix=prefix, service=service, label="ColdHead PAUSE", operation=f70_op.coldhead_pause)

        with c3:
            if st.button("Reset", width="stretch", disabled=send_disabled, key=_k(prefix, "reset")):
                assert service is not None
                _render_control_confirm_dialog(prefix=prefix, service=service, label="Reset", operation=f70_op.reset)


def _render_last_result_panel(prefix: str) -> None:
    with st.container(border=True):
        st.subheader("Last Result")
        result = cast(dict[str, Any], st.session_state[_k(prefix, "last_result")])
        if not result:
            st.info("No command has been executed yet.")
            return

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Status", "Success" if result.get("ok") else "Error")
        with c2:
            st.metric("Command", str(result.get("label", "N/A")))
        with c3:
            st.metric("Latency", f"{result.get('elapsed_ms', 0.0)} ms")

        if result.get("ok"):
            st.code(str(result.get("raw", "")), language="text")
            st.json(result.get("parsed", {}))
        else:
            st.error(str(result.get("error", "Unknown error")))


def _render_last_read_status_panel(prefix: str) -> None:
    with st.container(border=True):
        st.subheader("Last ReadStatus")
        payload = cast(dict[str, Any], st.session_state[_k(prefix, "last_read_status")])
        if not payload:
            st.info("ReadStatus has not been executed yet.")
            return

        c1, c2, c3 = st.columns(3)
        parsed = cast(dict[str, Any], payload.get("parsed", {}))
        with c1:
            st.metric("Updated At", str(payload.get("timestamp", "N/A")))
        with c2:
            state_number = cast(str, parsed.get("state_number", "N/A"))
            st.metric("State", state_number)
        with c3:
            system_on = bool(parsed.get("system_on", False))
            st.metric("System", "ON" if system_on else "OFF")
        alarms = cast(dict[str, bool], parsed.get("alarms", {}))
        active_alarms = [name for name, active in alarms.items() if active]
        st.caption("Active Alarms: " + (", ".join(active_alarms) if active_alarms else "None"))


def _render_history_panel(prefix: str) -> None:
    with st.container(border=True):
        st.subheader("Command History")
        status_filter = st.selectbox(
            "Filter",
            ["all", "success", "error", "timeout"],
            index=0,
            key=_k(prefix, "history_filter"),
        )
        history = cast(list[dict[str, Any]], st.session_state[_k(prefix, "command_history")])

        if status_filter == "all":
            rows = history
        else:
            rows = [row for row in history if row.get("status") == status_filter]

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Clear History", width="stretch", key=_k(prefix, "clear_history")):
                st.session_state[_k(prefix, "command_history")] = []
                st.rerun()
        with c2:
            st.caption(f"Rows: {len(rows)} (max retained: 100)")

        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("No history to display.")


def _render_log_panel(prefix: str) -> None:
    with st.container(border=True):
        st.subheader("Log")
        st.caption("This panel uses the shared app logger. File persistence is optional.")

        persist_key = _k(prefix, "persist_enabled")
        persist_enabled = st.toggle("Enable File Persistence", key=persist_key)
        default_path = str(Path("logs") / "f70_command_console.log")
        log_path_key = _k(prefix, "log_path")
        log_path = st.text_input("Log File Path", value=cast(str, st.session_state.get(log_path_key, default_path)), key=log_path_key)

        file_sub_key = _k(prefix, "file_subscriber")
        current_file_sub = cast(FileLogSubscriber | None, st.session_state.get(file_sub_key))
        if persist_enabled and current_file_sub is None:
            file_sub = FileLogSubscriber(file_path=log_path, detailed=True)
            get_app_logger().subscribe(file_sub, min_level=LogLevel.INFO)
            st.session_state[file_sub_key] = file_sub
            get_app_logger().info("File persistence enabled.", source="F70Console", context={"path": log_path})
        elif (not persist_enabled) and current_file_sub is not None:
            get_app_logger().unsubscribe(current_file_sub)
            st.session_state[file_sub_key] = None
            get_app_logger().info("File persistence disabled.", source="F70Console")

        log_sub_key = _k(prefix, "log_subscriber")
        if log_sub_key not in st.session_state:
            ui_sub = StreamlitConsoleSubscriber(max_lines=200)
            get_app_logger().subscribe(ui_sub, min_level=LogLevel.INFO)
            st.session_state[log_sub_key] = ui_sub

        log_sub = cast(StreamlitConsoleSubscriber, st.session_state[log_sub_key])
        log_sub.render_to_streamlit(clear_button_key=_k(prefix, "log_console_clear"))


def _init_state(prefix: str) -> None:
    st.session_state.setdefault(_k(prefix, "last_result"), {})
    st.session_state.setdefault(_k(prefix, "last_read_status"), {})
    st.session_state.setdefault(_k(prefix, "command_history"), [])
    st.session_state.setdefault(_k(prefix, "persist_enabled"), False)


def render_f70_command_console_component(
    *,
    service: SerialServiceLike | None,
    mode_label: str,
    port: str,
    baudrate: int,
    key_prefix: str = "f70_console",
    disable_control_commands: bool = False,
) -> None:
    _init_state(key_prefix)

    st.caption(f"Mode: {mode_label} / Port: {port} / Baudrate: {baudrate}")

    left, right = st.columns(2)
    with left:
        _render_read_panel(key_prefix, service)
    with right:
        _render_control_panel(key_prefix, service, force_disabled=disable_control_commands)

    _render_last_result_panel(key_prefix)
    _render_last_read_status_panel(key_prefix)
    _render_history_panel(key_prefix)
    _render_log_panel(key_prefix)
