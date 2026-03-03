import asyncio
import threading
import serial
import streamlit as st
from f70_automate.serial_service import SerialAsyncManager
from f70_automate.wavelogger import wlx_thread 
import f70_automate.resources as local_resources


@st.cache_resource(on_release=lambda ml: asyncio.run_coroutine_threadsafe(ml[0].stop(), st.session_state._loop_serial).result())
def get_serial_async_manager_cached():
    """
    非同期マネージャーと、それを動かすためのイベントループスレッドを生成。
    """
    # 1. シリアルポートの準備 (FILEパスなどは環境に合わせて固定)
    ser = serial.Serial("COM3", 9600, timeout=1) 
    manager = SerialAsyncManager(ser)
    
    # 2. 専用のイベントループを作成し、別スレッドで実行
    loop = asyncio.new_event_loop()
    
    def run_loop(loop):
        asyncio.set_event_loop(loop)
        async def main():
            async with manager:
                while not manager._stop_event.is_set():
                    await asyncio.sleep(0.1)
        loop.run_until_complete(main())

    t = threading.Thread(target=run_loop, args=(loop,), daemon=True)
    t.start()
    
    # 3. ループを後で参照できるように保持（クリーンアップ等で必要）
    st.session_state._loop_serial = loop
    
    return manager, loop

@st.cache_resource(on_release=lambda wlx_logger: wlx_logger.stop())
def get_wlx_logger_cached() -> wlx_thread.WLXDataLogger:
    _FIXED_FILE = local_resources.get_path("sequential_capture.xcf")
    wlx_logger = wlx_thread.WLXDataLogger(_FIXED_FILE)
    wlx_logger.daemon = True  # ゾンビ化しないようにデーモンスレッドに設定
    wlx_logger._data = []
    return wlx_logger
