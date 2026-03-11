import asyncio
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Callable

import serial

from f70_automate._core.serial import serial_async


class SerialServiceError(RuntimeError):
    pass


class SerialServiceTimeoutError(TimeoutError, SerialServiceError):
    pass


class SerialService:
    def __init__(
        self,
        ser: serial.Serial,
        loop: asyncio.AbstractEventLoop | None = None,
        *,
        default_timeout: float = 10.0,
        startup_timeout: float = 5.0,
    ):
        self._closed = False
        self._port = ser
        self._default_timeout = default_timeout
        self._startup_timeout = startup_timeout
        self._loop_ready = threading.Event()
        self._loop_thread: threading.Thread | None = None
        self._owns_loop = loop is None
        self._loop = loop if loop is not None else asyncio.new_event_loop()

        if self._owns_loop:
            self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
            self._loop_thread.start()
            if not self._loop_ready.wait(timeout=self._startup_timeout):
                raise SerialServiceError("Event loop startup timed out.")
        else:
            self._loop_ready.set()

        self._actor = serial_async.SerialAsyncManager(self._port, default_timeout=default_timeout)
        try:
            asyncio.run_coroutine_threadsafe(self._actor.start(), self._loop).result(timeout=self._startup_timeout)
        except FutureTimeoutError as exc:
            raise SerialServiceTimeoutError("Serial actor startup timed out.") from exc

    @classmethod
    def create(
        cls,
        port: str,
        baudrate: int,
        *,
        timeout: float = 1.0,
        default_timeout: float = 10.0,
        startup_timeout: float = 5.0,
        **serial_kwargs: Any,
    ) -> "SerialService":
        ser = serial.Serial(port, baudrate=baudrate, timeout=timeout, **serial_kwargs)
        return cls(
            ser,
            loop=None,
            default_timeout=default_timeout,
            startup_timeout=startup_timeout,
        )

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        self._loop.run_forever()

    def __enter__(self) -> "SerialService":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.shutdown()

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def is_alive(self) -> bool:
        thread_alive = self._loop_thread.is_alive() if self._loop_thread is not None else self._loop.is_running()
        return (not self._closed) and self._actor.is_alive() and thread_alive

    @property
    def port_name(self) -> str:
        return str(self._port.port)

    @property
    def baudrate(self) -> int:
        return int(self._port.baudrate)

    def call(self, fn: Callable[..., Any], *a: Any, timeout: float | None = None, **kw: Any) -> Any:
        if self._closed:
            raise RuntimeError("SerialService is closed.")

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            raise RuntimeError("SerialService.call() called from actor loop thread.")

        fut = asyncio.run_coroutine_threadsafe(
            self._actor.run_task(fn, *a, **kw),
            self._loop,
        )
        wait_timeout = self._default_timeout if timeout is None else timeout
        try:
            return fut.result(timeout=wait_timeout)
        except FutureTimeoutError as exc:
            fut.cancel()
            raise SerialServiceTimeoutError(f"SerialService.call timed out after {wait_timeout} seconds.") from exc
        except serial.SerialException as exc:
            raise SerialServiceError(f"Serial error: {exc}") from exc

    __call__ = call

    def call_checked(self, op: Any, *a: Any, timeout: float | None = None, **kw: Any) -> Any:
        if not callable(op):
            raise TypeError("op must be callable.")
        if not hasattr(op, "can_execute"):
            raise TypeError("op must implement can_execute(ser).")

        def _checked_runner(ser: serial.Serial, operation: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
            if not operation.can_execute(ser):
                op_name = getattr(operation, "name", repr(operation))
                raise RuntimeError(f"Operation '{op_name}' cannot execute in current state.")
            return operation(ser, *args, **kwargs)

        return self.call(_checked_runner, op, a, kw, timeout=timeout)

    def close(self) -> None:
        self.shutdown()

    def shutdown(self) -> None:
        if self._closed:
            return

        self._closed = True
        stop_error = None
        try:
            asyncio.run_coroutine_threadsafe(self._actor.stop(), self._loop).result(timeout=self._default_timeout)
        except Exception as exc:  # noqa: BLE001
            stop_error = exc

        if self._owns_loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._loop_thread is not None:
                self._loop_thread.join(timeout=self._default_timeout)

        if self._port.is_open:
            self._port.close()

        if stop_error is not None:
            raise SerialServiceError(f"SerialService shutdown failed: {stop_error}") from stop_error
