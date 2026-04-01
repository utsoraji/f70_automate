from __future__ import annotations

from typing import cast

import streamlit as st

from f70_automate._core.serial import SerialService
from f70_automate.apps.dashboards.f70_command_console_component import (
    SerialServiceLike,
    render_f70_command_console_component,
)
from f70_automate.tests.mock.fake_serial_f70 import F70Responder
from f70_automate.tests.mock.fake_serial_service import FakeSerialService


@st.cache_resource(on_release=lambda svc: svc.shutdown())
def get_serial_service(port: str, baudrate: int, use_mock: bool) -> SerialServiceLike:
    if use_mock:
        responder = F70Responder(
            system_on=False,
            temperatures=(45.0, 28.0, 26.5, 25.0),
            pressures=(1.15, 0.92),
            version="FAKE-CONSOLE-1.0",
            elapsed_hours=123.4,
        )
        return FakeSerialService(responder=responder, port="MOCK", baudrate=baudrate)
    return SerialService.create(port, baudrate, timeout=1.0, default_timeout=10.0)


def _render_connection_panel() -> tuple[SerialServiceLike | None, bool, str, int]:
    st.subheader("Connection")
    left, right = st.columns(2)
    with left:
        use_mock = st.toggle("Use Mock Devices", value=True)
    with right:
        st.caption("Mock mode is recommended for initial validation.")

    c1, c2 = st.columns(2)
    with c1:
        port = st.text_input("Port", value="COM3", disabled=use_mock)
    with c2:
        baudrate = st.number_input("Baudrate", min_value=1200, max_value=115200, value=9600, step=1200)

    service: SerialServiceLike | None = None
    try:
        service = get_serial_service(port, int(baudrate), use_mock)
    except Exception as exc:
        st.error(f"Service initialization failed: {exc}")

    is_connected = bool(service and service.is_alive and not service.closed)
    st.metric("Serial State", "Connected" if is_connected else "Disconnected")

    if st.button("Reconnect", width="stretch"):
        get_serial_service.clear()
        st.rerun()

    return service, use_mock, port, int(baudrate)


def main() -> None:
    st.set_page_config(page_title="F70 Command Console", layout="wide")
    st.title("F70 Command Console")
    st.caption("Read commands and control commands are split at component level.")

    service, use_mock, port, baudrate = _render_connection_panel()
    render_f70_command_console_component(
        service=service,
        mode_label="Mock" if use_mock else "Hardware",
        port=port,
        baudrate=baudrate,
        key_prefix="f70_console_standalone",
    )


if __name__ == "__main__":
    main()
