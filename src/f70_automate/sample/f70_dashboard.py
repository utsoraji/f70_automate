import asyncio
import threading
import serial
import streamlit as st
from f70_automate.f70_serial import f70_operation as f70_safe
from f70_automate.serial_service import SerialService





@st.cache_resource
def get_serial_service_cached() -> SerialService:
    """
    シリアルサービスを生成して返す。Streamlitのキャッシュ機能を利用して、セッションごとに1つのインスタンスを保持。
    """
    loop = asyncio.new_event_loop()
    ser = serial.Serial("COM3", 9600)
    service = SerialService(ser, loop)

    return service


ser = get_serial_service_cached()


st.session_state.setdefault("toggle", False)


st.title(":chart: F70 State Dashboard")


st.toggle("データ取得", key="toggle", on_change=None)
placeholder = st.empty()


@st.fragment(run_every=1 if st.session_state.toggle else None)
def update_state():
    status_data = ser.call(f70_safe.read_status)

    st.title("Device Control Dashboard")

    # 1行目にサマリーを並べる
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(label="System Power", value=status_data.system_on)

    with col2:
        st.metric(label="Configuration", value=status_data.config_mode.name)

    with col3:
        st.metric(label="State Number", value=status_data.state_number.name)

    st.divider()

    # 2行目に詳細情報を配置
    col4, col5 = st.columns(2)

    with col4:
        st.write("### Solenoid Status")
        if status_data.solenoid_on:
            st.success("SOLENOID: ON")
        else:
            st.error("SOLENOID: OFF")

    with col5:
        st.write("### Active Alarms")
        if not status_data.oil_alarm and not status_data.pressure_alarm and not status_data.water_flow_alarm and not status_data.water_temp_alarm and not status_data.helium_temp_alarm and not status_data.phase_alarm and not status_data.motor_temp_alarm:
            st.info("No active alarms")
        else:
            if status_data.pressure_alarm:
                st.warning("Pressure Alarm")
            if status_data.oil_alarm:
                st.warning("Oil Level Alarm")
            if status_data.water_flow_alarm:
                st.warning("Water Flow Alarm")
            if status_data.water_temp_alarm:
                st.warning("Water Temperature Alarm")

update_state()

