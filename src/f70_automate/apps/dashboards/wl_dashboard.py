import time

import streamlit as st

import f70_automate.resources as local_resources
from f70_automate.domains.wavelogger import WLXRuntime


@st.cache_resource(on_release=lambda runtime: runtime.runner.stop())
def get_wlx_runtime_cached() -> WLXRuntime:
    fixed_file = local_resources.get_path("sequential_capture.xcf")
    runtime = WLXRuntime.create(filepath=fixed_file)
    runtime.runner.daemon = True
    return runtime


st.session_state.setdefault("toggle", get_wlx_runtime_cached().runner.is_alive())

st.title(":chart: WaveLoggerX Data Visualization")


def toggle() -> None:
    runtime = get_wlx_runtime_cached()
    if st.session_state.toggle:
        if not runtime.runner.is_alive():
            get_wlx_runtime_cached.clear()
            runtime = get_wlx_runtime_cached()
            runtime.runner.start()
            with st.spinner("Waiting for acquisition to become ready..."):
                while (
                    runtime.store.get_current_physical(runtime.store.default_channel) is None
                    and runtime.runner.is_alive()
                ):
                    time.sleep(0.1)
                runtime.store.check_exception()
    else:
        runtime.runner.stop()


st.toggle("WaveLogger Acquisition", key="toggle", on_change=toggle)
placeholder = st.empty()


@st.fragment(run_every=1 if st.session_state.toggle else None)
def update_chart() -> None:
    runtime = get_wlx_runtime_cached()
    default_channel = runtime.store.default_channel
    current_value = None
    if runtime.runner.is_alive():
        current_value = runtime.store.get_current_physical(default_channel)
    if runtime.runner.is_alive() and current_value is not None:
        placeholder.line_chart(runtime.store.get_physical_history(default_channel))
        st.write(f"Latest value: {current_value}")
    elif st.session_state.toggle:
        st.warning("Acquisition has not produced a sample yet.")
    else:
        st.warning("Acquisition is stopped.")


update_chart()
