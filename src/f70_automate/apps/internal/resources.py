import asyncio
import threading

import serial
import streamlit as st

import f70_automate.apps.internal.resources as local_resources
from f70_automate._core.serial.serial_async import SerialAsyncManager
from f70_automate.domains.wavelogger import wlx_thread


@st.cache_resource(
    on_release=lambda ml: asyncio.run_coroutine_threadsafe(
        ml[0].stop(), st.session_state._loop_serial
    ).result()
)
def get_serial_async_manager_cached():
    ser = serial.Serial("COM3", 9600, timeout=1)
    manager = SerialAsyncManager(ser)

    loop = asyncio.new_event_loop()

    def run_loop(loop):
        asyncio.set_event_loop(loop)

        async def main():
            async with manager:
                while not manager._stop_event.is_set():
                    await asyncio.sleep(0.1)

        loop.run_until_complete(main())

    thread = threading.Thread(target=run_loop, args=(loop,), daemon=True)
    thread.start()

    st.session_state._loop_serial = loop

    return manager, loop


@st.cache_resource(on_release=lambda runtime: runtime.runner.stop())
def get_wlx_logger_cached() -> wlx_thread.WLXRuntime:
    fixed_file = local_resources.get_path("sequential_capture.xcf")
    runtime = wlx_thread.WLXRuntime.create(filepath=fixed_file)
    runtime.runner.daemon = True
    return runtime
