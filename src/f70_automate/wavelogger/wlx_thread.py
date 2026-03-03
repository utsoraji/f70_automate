import threading
import time
from f70_automate.wavelogger import wlx_wrapper
from pathlib import Path

class WLXDataLogger(threading.Thread):
	def __init__(self, filepath: Path | str):
		super().__init__()
		self._filepath = filepath
		self._active = False
		self.lock = threading.Lock()
		self._current_data = None
		self._data = []
		self._exception = None

	@property
	def current_data(self):
		self._check_exception()
		with self.lock:
			return self._current_data

	@property
	def data(self):
		self._check_exception()
		with self.lock:
			return self._data.copy()

	def run(self):
		self._active = True
		try:
			with wlx_wrapper.WaveLoggerApp(visible=True) as app:
				app.connector.setup_usb(device_id=0)
				app.measurement.load_settings(self._filepath)
				app.measurement.start()
				doc = app.get_active_document()

				while self._active: #main loop
					current_data = doc.get_current_data(1, 0)
					with self.lock:
						self._current_data = current_data

					data_count = doc.data_count
					with self.lock:
						local_data_count = len(self._data)

					data_to_append = [doc.get_data(1, 0, i) for i in range(local_data_count, data_count)]
					with self.lock:
						self._data.extend(data_to_append)
					time.sleep(1)
		except Exception as e:
			with self.lock:
				self._exception = e
		finally:
				self._active = False
	
	def wait_until_awake(self):
		while self._current_data is None and self._active:
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
			print(f"Current Data: {logger._current_data}")
		time.sleep(1)
	logger.stop()
