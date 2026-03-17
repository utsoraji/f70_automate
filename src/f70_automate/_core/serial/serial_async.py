import asyncio
from types import TracebackType
from typing import Callable, Concatenate, ParamSpec, Protocol, TypeVar

class SerialPortLike(Protocol):
	"""
	A minimal protocol representing the serial port interface needed by SerialAsyncManager.
	Based on pyserial's Serial class, but only includes the methods we actually use.
	"""
	def write(self, b: bytes, /) -> int | None: ...
	def read_until(self, expected: bytes = b"\r", size: int = 256) -> bytes: ...
	def close(self) -> None: ...
	@property
	def is_open(self) -> bool: ...
	@property
	def port(self) -> str | None: ...
	@property
	def baudrate(self) -> int: ...
	
P = ParamSpec("P")
R = TypeVar("R", covariant=True)

CommandFunc = Callable[Concatenate[SerialPortLike, P], R]

class _Command[R]:
	def __init__(self,  func: CommandFunc[P, R], *args: P.args, **kwargs: P.kwargs):
		self._func = func
		self._args = args
		self._kwargs = kwargs

	def __call__(self, ser: SerialPortLike) -> R:
		return self._func(ser, *self._args, **self._kwargs)

class SerialAsyncManager[R]:
	def __init__(self, ser: SerialPortLike, default_timeout: float = 10.0) -> None:
		self._ser: SerialPortLike = ser
		self._queue: asyncio.Queue[tuple[_Command[R], asyncio.Future[R]]] = asyncio.Queue()
		self._stop_event = asyncio.Event()
		self._worker_task = None
		self.default_timeout = default_timeout

	async def __aenter__(self) -> "SerialAsyncManager":
		"""async with 開始時にワーカーを自動起動"""
		self._worker_task = asyncio.create_task(self._worker())
		return self

	async def __aexit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
		"""async with 終了時に自動で安全停止・クローズ"""
		await self.stop()

	async def _worker(self) -> None:
		"""唯一シリアルポートを操作するタスク"""
		print("Worker: Started")
		try:
			while True:
				if self._stop_event.is_set() and self._queue.empty():
					break

				try:
					# 0.5秒ごとに停止命令をチェックしつつキューを待機
					command, future = await asyncio.wait_for(self._queue.get(), timeout=0.5)
				except asyncio.TimeoutError:
					continue

				try:
					loop = asyncio.get_running_loop()
					result = await loop.run_in_executor(None, command, self._ser)
					future.set_result(result)
				except Exception as e:
					future.set_exception(e)
				finally:
					self._queue.task_done()

		except asyncio.CancelledError:
			print("Worker: Cancelled")
		finally:
			# 確実なクローズ
			if self._ser and self._ser.is_open:
				self._ser.close()
				print("Worker: Serial port closed.")

	async def run_task(
		self,
		func: CommandFunc[P, R]
		, *args: P.args, **kwargs: P.kwargs
	) -> R:
		"""
		外部から通信タスク（read_status等）を依頼する。必ずtimeoutでロック回避（デフォルトはインスタンス設定値）
		"""
		if self._stop_event.is_set():
			raise RuntimeError("Manager is stopping or stopped.")
		
		future = asyncio.get_running_loop().create_future()
		await self._queue.put((_Command(func, *args, **kwargs), future))
		return await asyncio.wait_for(future, timeout=self.default_timeout)
	
	async def start(self) -> None:
		"""明示的にワーカーを起動させたい場合に呼び出す（async with での自動起動も可能）"""
		if self._worker_task is None or self._worker_task.done():
			self._worker_task = asyncio.create_task(self._worker())

	async def stop(self) -> None:
		"""
		Manager will not accept new commands.
		All accepted commands will finish.
		Some results may still be delivered after stop() returns.
		"""
		self._stop_event.set()
		if self._worker_task:
			await self._queue.join() # すべてのタスクが完了するのを待つ
			self._worker_task.cancel()
			try:
				await self._worker_task
			except asyncio.CancelledError:
				pass

	def is_alive(self) -> bool:
		return self._worker_task is not None and not self._worker_task.done()
