from pathlib import Path
import time
import win32com.client
import pythoncom
from enum import IntEnum
from typing import Optional, List, Tuple

# --- 列挙型定義 ---
class LoggerState(IntEnum):
	IDLE = 1
	START_WAIT = 2
	TRIGGER_WAIT = 3
	RUN = 4
	REPEAT_RUN = 5
	PRE_TRIGGER = 6
	POST_TRIGGER = 7
	STOP_WAIT = 8
	DATA_REMAIN = 9
	READ_WAIT = 10
	BUSY = 11
	PROCEDURE_WAIT = 12
	UNKNOWN = -1

class DeviceID(IntEnum):
	NR500_USB_0 = 0
	NRX100_USB_0 = 4
	NRX100_LAN_0 = 8

class StartUpState(IntEnum):
	DISCONNECTED = 0
	STARTING = 1
	READY = 2

class UnitInfo(IntEnum):
	NOT_CONNECTED = 0
	NR_TH08 = 129
	NR_HA08 = 130
	NR_ST04 = 131
	NR_C512 = 134
	NR_CA04 = 136
	NR_HV04 = 137
	NR_FV04 = 139
	NR_EN16 = 140
	NR_XTH08T = 141
	NR_XHA08T = 142
	NR_CF512 = 143
	NR_500 = 193
	NR_X100 = 198
	NR_XR01 = 199
	ENV_UNIT = 200  # 耐環境ユニット
	COMM_ERROR = -2  # 本体と通信できません
	INVALID_ARG = -3  # 不正な引数が指定されました


FLOAT_MAX = 3.4028234663852886e+38

# --- カスタム例外 ---
class WaveLoggerError(Exception):
	"""WaveLoggerXからのエラーコードを保持する例外クラス"""
	def __init__(self, message, error_code):
		self.error_code = hex(error_code) if isinstance(error_code, int) else error_code
		super().__init__(f"{message} (Error: {self.error_code})")

# --- コンポーネントクラス ---

class DeviceConnector:
	"""通信設定を担当するクラス"""
	def __init__(self, app_obj):
		self._app = app_obj

	def setup_usb(self, device_id: int):
		print(f"Setting USB Identifier to {device_id}")
		res = self._app.SetIdentifier(device_id)
		if res != 0: raise WaveLoggerError("USB識別子の設定に失敗しました", res)

	def setup_lan(self, lan_index: int, ip_address: str, port: int = 24682):
		"""lan_index: 0-3 (NRX100_LAN_ID0～3に対応)"""
		# SetIdentifierには 8 + index を渡す
		self._app.SetIdentifier(lan_index + 8)
		ip_parts = [int(x) for x in ip_address.split('.')]
		res = self._app.SetLanConfig(lan_index, *ip_parts, port)
		if res != 0: raise WaveLoggerError("LAN設定の送信に失敗しました", res)
		
		res = self._app.ConnectLan
		if res != 0: raise WaveLoggerError("LAN接続に失敗しました", res)
	
	def get_unit_info(self):
		"""接続されたユニットの情報を取得"""
		return UnitInfo(self._app.GetUnitInfo(0))
	
	@property
	def startup_state(self) -> StartUpState:
		"""現在の起動状態を取得"""
		return StartUpState(self._app.GetStartupState)
	
class WaveLoggerDocument:
	"""ドキュメント（データファイル）操作を担当するクラス"""
	def __init__(self, doc_obj):
		self._doc = doc_obj

	@property
	def data_count(self) -> int:
		"""現在のサンプリングデータ数"""
		return self._doc.GetDataCount
	
	def get_data(self, unit_id: int, channel_id: int, pos: int) -> float:
		"""指定したチャネル・位置の物理値を取得"""
		return self._doc.GetData(unit_id, channel_id, pos)

	def get_current_data(self, unit_id: int, channel_id: int) -> float | None:
		"""指定したチャネルの最新データを取得"""
		value = self._doc.GetCurrentData(unit_id, channel_id)
		return value if value < FLOAT_MAX else None
	
	def save_as(self, file_path: str):
		"""計測データを保存 (.wre)"""
		res = self._doc.Save(file_path)
		if res != 0: raise WaveLoggerError("ファイルの保存に失敗しました", res)

class MeasurementController:
	"""計測動作を制御するクラス"""
	def __init__(self, app_obj):
		self._app = app_obj

	def load_settings(self, path: Path | str):
		res = self._app.OpenFile(str(path))
		if res != 0: raise WaveLoggerError("設定ファイルの読み込みに失敗しました", res)

	def start(self):
		res = self._app.Start
		if res != 0: raise WaveLoggerError("計測開始に失敗しました", res)
	
	def wait_for_completion(self, check_interval: float = 0.1):
		"""計測完了まで待機"""
		while True:
			state = LoggerState(self._app.GetState)
			if state == LoggerState.IDLE:
				break
			time.sleep(check_interval)

	def stop(self):
		self._app.Stop()

# --- メインアプリケーションクラス ---

class WaveLoggerApp:
	"""WaveLoggerX全体を管理するメインクラス"""
	def __init__(self, visible: bool = True):
		self._app = None
		self._visible = visible
		self._connector: Optional[DeviceConnector] = None
		self._measurement: Optional[MeasurementController] = None

	def launch(self):
		"""アプリの起動と初期化"""
		pythoncom.CoInitialize()
		self._app = win32com.client.Dispatch("WaveLoggerX.Application")
		self._app.Initialize()  # 必須
		self._app.Visible = self._visible
		
		# 子コンポーネントの初期化
		self._connector = DeviceConnector(self._app)
		self._measurement = MeasurementController(self._app)
		return self

	def quit(self):
		"""クリーンアップ処理"""
		if self._app:
			if self.is_logging and self.measurement:
				self.measurement.stop()
			self._app.Quit()          # 必須
			self._app = None

	@property
	def is_visible(self) -> bool:
		return self._app.Visible if self._app else False
	
	@property
	def connector(self) -> DeviceConnector:
		if not self._connector:
			raise RuntimeError("アプリが起動していません。")
		return self._connector

	@property
	def measurement(self) -> MeasurementController:
		if not self._measurement:
			raise RuntimeError("アプリが起動していません。")
		return self._measurement

	@property
	def state(self) -> LoggerState:
		return LoggerState(self._app.GetState) if self._app else LoggerState.UNKNOWN

	@property
	def is_logging(self) -> bool:
		"""マニュアルの各状態に基づき計測中かを判定"""
		return self.state in {
			LoggerState.START_WAIT, LoggerState.TRIGGER_WAIT, LoggerState.RUN,
			LoggerState.REPEAT_RUN, LoggerState.PRE_TRIGGER, LoggerState.POST_TRIGGER,
			LoggerState.STOP_WAIT, LoggerState.READ_WAIT, LoggerState.PROCEDURE_WAIT
		}

	def get_active_document(self) -> WaveLoggerDocument:
		"""現在のアクティブドキュメントをラップして返す"""
		if not self._app:
			raise RuntimeError("アプリが起動していません。")
		raw_doc = self._app.GetActiveFile
		if raw_doc is None:
			raise WaveLoggerError("アクティブなドキュメントが見つかりません", "NoActiveDocument")
		return WaveLoggerDocument(raw_doc)

	# Context Manager support
	def __enter__(self): return self.launch()
	def __exit__(self, exc_type, exc_val, exc_tb): self.quit()

# --- 使用例 ---
if __name__ == "__main__":
	import f70_automate.resources as local_resources
	FILE = local_resources.get_path("sequential_capture.xcf")
	with WaveLoggerApp(visible=True) as app:
		app.connector.setup_usb(device_id=0)
		app.measurement.load_settings(FILE)
		app.measurement.start()

		while True:
			doc = app.get_active_document()
			# print(doc.get_current_data(1, 0))
			print(f"{doc.data_count}: {doc._doc.GetData(1, 0, doc.data_count - 1)}")  # 最新データの物理値

			time.sleep(1)
