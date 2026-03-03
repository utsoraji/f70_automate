import streamlit as st
from f70_automate.wavelogger import wlx_thread 
import f70_automate.resources as local_resources

@st.cache_resource(on_release=lambda wlx_logger: wlx_logger.stop())
def get_wlx_logger_cached() -> wlx_thread.WLXDataLogger:
    _FIXED_FILE = local_resources.get_path("sequential_capture.xcf")
    wlx_logger = wlx_thread.WLXDataLogger(_FIXED_FILE)
    wlx_logger.daemon = True  # ゾンビ化しないようにデーモンスレッドに設定
    wlx_logger._data = []
    return wlx_logger

st.session_state.setdefault("toggle", get_wlx_logger_cached().is_alive())

st.title(":chart: WaveLoggerX Data Visualization")

def toggle():
    if st.session_state.toggle:
        if not get_wlx_logger_cached().is_alive():
            get_wlx_logger_cached.clear()      
            get_wlx_logger_cached().start()
            get_wlx_logger_cached()._data = []
            with st.spinner("データ取得開始まで待機中..."):
                get_wlx_logger_cached().wait_until_awake()
    else:
        get_wlx_logger_cached().stop()

st.toggle("データ取得", key="toggle", on_change=toggle)
placeholder = st.empty()

@st.fragment(run_every=1 if st.session_state.toggle else None)
def update_chart():
    wlx_logger = get_wlx_logger_cached()
    if wlx_logger.is_alive() and wlx_logger._current_data is not None:
        placeholder.line_chart(wlx_logger.data )
        st.write(f"最新値: {wlx_logger.current_data}")
    elif st.session_state.toggle:
        st.warning("データ取得が停止しました。")
    else:
        st.warning("データ取得停止中")

update_chart()
