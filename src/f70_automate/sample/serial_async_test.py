import asyncio
from f70_automate.serial_service.serial_async import SerialAsyncManager
from f70_automate.f70_serial import f70_safe_operation as f70_safe

def connect_serial():
    """シリアル接続を確立して返す"""
    # ここでは例としてCOM3を使用。実際には環境に合わせて変更してください。
    import serial
    ser = serial.Serial("COM3", baudrate=9600, timeout=1)
    return ser

async def test_serial_async():
    async with SerialAsyncManager(connect_serial()) as serial_manager:
        for _ in range(5):  # 5回データを取得して表示
            status_data = await serial_manager.run_task(f70_safe.read_status)
            print(status_data)
            await asyncio.sleep(1)  # 1秒待機（実際のアプリではUI更新のタイミングなどに合わせて調整）

if __name__ == "__main__":
    asyncio.run(test_serial_async())