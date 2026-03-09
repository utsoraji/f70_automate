import threading
import time
from pathlib import Path
from typing import Callable

from f70_automate.wavelogger.channel_config import ChannelConfig
from f70_automate.wavelogger import wlx_wrapper


DEFAULT_CHANNEL = ChannelConfig(
	key="default",
	label="Channel 0",
	unit_id=1,
	channel_id=0,
)


class WLXDataLogger(threading.Thread):
	def __init__(
		self,
		filepath: Path | str,
		app_factory: Callable[[], wlx_wrapper.WaveLoggerApp] | None = None,
		poll_interval: float = 1.0,
		channels: tuple[ChannelConfig, ...] | None = None,
	):
		super().__init__()
		self._filepath = filepath
		self._app_factory = app_factory or (lambda: wlx_wrapper.WaveLoggerApp(visible=True))
		self._poll_interval = poll_interval
		self._channels = channels or (DEFAULT_CHANNEL,)
		self._default_channel = self._channels[0]
		self._active = False
		self.lock = threading.Lock()
		self._current_voltage = {channel.key: None for channel in self._channels}
		self._current_physical = {channel.key: None for channel in self._channels}
		self._voltage_data = {channel.key: [] for channel in self._channels}
		self._physical_data = {channel.key: [] for channel in self._channels}
		self._exception = None

	@property
	def channels(self) -> tuple[ChannelConfig, ...]:
		return self._channels

	@property
	def current_data(self):
		return self.get_current_physical(self._default_channel)

	@property
	def data(self):
		return self.get_physical_history(self._default_channel)

	@property
	def current_physical_values(self) -> dict[str, float | None]:
		self._check_exception()
		with self.lock:
			return self._current_physical.copy()

	def get_current_voltage(self, channel: ChannelConfig) -> float | None:
		self._check_exception()
		with self.lock:
			return self._current_voltage[channel.key]

	def get_current_physical(self, channel: ChannelConfig) -> float | None:
		self._check_exception()
		with self.lock:
			return self._current_physical[channel.key]

	def get_voltage_history(self, channel: ChannelConfig) -> list[float | None]:
		self._check_exception()
		with self.lock:
			return self._voltage_data[channel.key].copy()

	def get_physical_history(self, channel: ChannelConfig) -> list[float | None]:
		self._check_exception()
		with self.lock:
			return self._physical_data[channel.key].copy()

	def run(self):
		self._active = True
		try:
			with self._app_factory() as app:
				app.connector.setup_usb(device_id=0)
				app.measurement.load_settings(self._filepath)
				app.measurement.start()
				doc = app.get_active_document()

				while self._active: #main loop
					data_count = doc.data_count
					with self.lock:
						local_data_count = len(self._voltage_data[self._default_channel.key])

					current_voltage: dict[str, float | None] = {}
					current_physical: dict[str, float | None] = {}
					voltage_to_append: dict[str, list[float | None]] = {}
					physical_to_append: dict[str, list[float | None]] = {}
					for channel in self._channels:
						voltage = doc.get_current_data(channel.unit_id, channel.channel_id)
						current_voltage[channel.key] = voltage
						current_physical[channel.key] = channel.voltage_to_physical(voltage)
						channel_voltage_data = [
							doc.get_data(channel.unit_id, channel.channel_id, i)
							for i in range(local_data_count, data_count)
						]
						voltage_to_append[channel.key] = channel_voltage_data
						physical_to_append[channel.key] = [
							channel.voltage_to_physical(value)
							for value in channel_voltage_data
						]

					with self.lock:
						self._current_voltage.update(current_voltage)
						self._current_physical.update(current_physical)
						for channel in self._channels:
							self._voltage_data[channel.key].extend(voltage_to_append[channel.key])
							self._physical_data[channel.key].extend(physical_to_append[channel.key])
					time.sleep(self._poll_interval)
		except Exception as e:
			with self.lock:
				self._exception = e
		finally:
				self._active = False
	
	def wait_until_awake(self):
		while self.get_current_physical(self._default_channel) is None and self._active:
			time.sleep(0.1)
		self._check_exception()
		
	def stop(self):
		with self.lock:
			self._active = False

	def _check_exception(self):
		with self.lock:
			if self._exception:
				raise self._exception



if __name__ == "__main__":
	# Test the WLXDataLogger class
	import f70_automate.resources as local_resources
	FILE = local_resources.get_path("sequential_capture.xcf")

	logger = WLXDataLogger(FILE)
	logger.start()

	logger.wait_until_awake()
	for _ in range(5):
		with logger.lock:
			print(f"Current Data: {logger.current_physical_values}")
		time.sleep(1)
	logger.stop()
