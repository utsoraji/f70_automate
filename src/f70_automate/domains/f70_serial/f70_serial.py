from enum import IntEnum, StrEnum
import dataclasses

from serial import Serial

class F70Command(StrEnum):
	ReadAllTemps = "TEA"
	ReadTemp1 = "TE1" # Complessor capsule helium discharge temperature
	ReadTemp2 = "TE2" # Water outlet temperature
	ReadTemp3 = "TE3" # Water inlet temperature
	ReadTemp4 = "TE4" # Unused
	ReadAllPressures = "PRA"
	ReadPressure1 = "PR1" # Complessor return pressure
	ReadPressure2 = "PR2" # Unused
	ReadStatesBits = "STA"
	ReadVersionAndElapsedHour = "ID1"
	PowerOn = "ON1"
	PowerOff = "OFF"
	Reset = "RS1"
	ColdHeadRun = "CHR"
	ColdHeadPause = "CHP"
	ColdHeadPauseOff = "POF"
	Invalid = "???"

class F70ConfigurationMode(StrEnum):
	MODE1 = "MODE1"
	MODE2 = "MODE2"

class F70StateNumber(IntEnum):
	LocalOff = 0
	LocalOn = 1
	RemoteOff = 2
	RemoteOn = 3    
	ColdHeadRun = 4
	ColdHeadPause = 5
	FaultOff = 6
	OilFaultOff = 7
	
@dataclasses.dataclass(frozen=True)
class CRC16_ansi:
	value: int
	
	@property
	def hex(self) -> str:
		return f"{self.value:04X}"
	
	@classmethod
	def from_data(cls, data: bytes) -> 'CRC16_ansi':
		crc = 0xFFFF
		for b in data:
			crc ^= b
			for _ in range(8):
				if crc & 0x0001:
					crc = (crc >> 1) ^ 0xA001
				else:
					crc >>= 1
		return cls(crc)
	
	@classmethod
	def from_hex(cls, hex_str: str) -> 'CRC16_ansi':
		value = int(hex_str, 16)
		return cls(value)


@dataclasses.dataclass(frozen=True)
class F70Frame:
	command: F70Command
	data: tuple[str, ...]
	crc: CRC16_ansi

	def __str__(self) -> str:
		buf = chr(0x24) + self.command + ","
		buf += ",".join(self.data)
		buf += "," + self.crc.hex
		return buf

	def as_bytes(self) -> bytes:
		return str(self).encode(encoding="ascii")


@dataclasses.dataclass(frozen=True)
class F70StatusBits:
	hex_str: str
	_val: int = dataclasses.field(init=False, repr=False)
	
	def __post_init__(self):
		object.__setattr__(self, '_val', int(self.hex_str, 16))
	
	def _get_bit(self, pos: int) -> bool:
		return (self._val >> pos) & 1 == 1

	@property # 15: Configuration mode
	def config_mode(self) -> F70ConfigurationMode:
		return F70ConfigurationMode.MODE2 if self._get_bit(15) else F70ConfigurationMode.MODE1
	@property # 11-9: MSbit of state number
	def state_number(self) -> F70StateNumber:
		return F70StateNumber((self._val >> 9) & 0b111)
	@property # 8: Solenoid On/Off
	def solenoid_on(self) -> bool:
		return self._get_bit(8)
	@property # 7: Pressure alarm
	def pressure_alarm(self) -> bool:
		return self._get_bit(7)
	@property # 6: Oil level alarm
	def oil_alarm(self) -> bool:
		return self._get_bit(6)
	@property # 5: Water flow alarm
	def water_flow_alarm(self) -> bool:
		return self._get_bit(5)
	@property # 4: Water temperature alarm
	def water_temp_alarm(self) -> bool:
		return self._get_bit(4)
	@property # 3: Helium temperature alarm
	def helium_temp_alarm(self) -> bool:
		return self._get_bit(3)
	@property # 2: Phase Sequence/Fuse alarm
	def phase_alarm(self) -> bool:  
		return self._get_bit(2)
	@property # 1: Motor Temperature alarm
	def motor_temp_alarm(self) -> bool:
		return self._get_bit(1) 
	@property # 0: System On/Off
	def system_on(self) -> bool:
		return self._get_bit(0)
	
	@property
	def alarms_active(self) -> bool:
		return any([
			self.pressure_alarm,
			self.oil_alarm,
			self.water_flow_alarm,
			self.water_temp_alarm,
			self.helium_temp_alarm,
			self.phase_alarm,
			self.motor_temp_alarm
		])
	
	def __str__(self) -> str:
		readable_str = f"Hex: {self.hex_str}\n"
		readable_str += f"System {'ON' if self.system_on else 'OFF'}\n"
		readable_str += f"Configuration Mode: {self.config_mode.name}\n"
		readable_str += f"State Number: {self.state_number.name}\n"
		readable_str += f"Solenoid: {'ON' if self.solenoid_on else 'OFF'}\n"
		if not (self.pressure_alarm or self.oil_alarm or self.water_flow_alarm or self.water_temp_alarm or self.helium_temp_alarm or self.phase_alarm or self.motor_temp_alarm):
			readable_str += "Alarms: No alarms\n"
		else:
			readable_str += "Alarms:\n"
			alarm_list = []
			if self.pressure_alarm:
				alarm_list.append("Pressure")
			if self.oil_alarm:
				alarm_list.append("Oil Level")
			if self.water_flow_alarm:
				alarm_list.append("Water Flow")
			if self.water_temp_alarm:
				alarm_list.append("Water Temperature")
			if self.helium_temp_alarm:
				alarm_list.append("Helium Temperature")
			if self.phase_alarm:
				alarm_list.append("Phase Sequence/Fuse")
			if self.motor_temp_alarm:
				alarm_list.append("Motor Temperature")
			readable_str += ",".join(alarm_list) + "\n"
		return readable_str

@dataclasses.dataclass(frozen=True)
class F70VersionAndElapsedHour:
	version: str
	elapsed_hours: float

	@classmethod
	def from_data(cls, data: tuple[str, ...]) -> 'F70VersionAndElapsedHour':
		if len(data) < 2:
			raise ValueError("Expected 2 data fields for version and elapsed hours")
		version = data[0]
		try:
			elapsed_hours = float(data[1])
		except ValueError:
			raise ValueError("Invalid format for elapsed hours")
		return cls(version=version, elapsed_hours=elapsed_hours)

	def __str__(self) -> str:
		return f"Version: {self.version}\nElapsed Hours: {self.elapsed_hours}"

def build_frame(command: F70Command, data: str = "") -> bytes:
	"""Build protocol frame:

	Start: 0x24
	Command: 3 ASCII letters
	Data: variable length
	CRC-16: 4 ASCII hex characters (uppercase) computed over Command+Data
	END: 0x0D
	"""
	if not isinstance(command, F70Command):
		raise ValueError("command must be an F70Command enum value")
	if command == F70Command.Invalid:
		raise ValueError("Invalid command is specified")

	try:
		cmd_bytes = command.encode("ascii")
	except UnicodeEncodeError:
		raise ValueError("command must be ASCII")

	if not isinstance(data, str):
		raise ValueError("data must be an ASCII string")
	try:
		data_bytes = data.encode("ascii")
	except UnicodeEncodeError:
		raise ValueError("data must be ASCII")

	
	body = '$'.encode("ascii") + cmd_bytes + data_bytes

	crc = CRC16_ansi.from_data(body)

	frame = bytearray()
	# frame.append(0x24)  # Start
	frame.extend(body)
	frame.extend(crc.hex.encode("ascii"))
	frame.append(0x0D)  # END (CR)
	return bytes(frame)

def parse_frame(frame: bytes) -> F70Frame:
	"""Parse protocol frame and return F70Response.
	Validate start byte, end byte, and CRC-16.
	"""
	if frame[0] != 0x24:
		raise ValueError(f"Invalid start byte: {frame[0]:02X}")

	if frame[-1] != 0x0D:
		raise ValueError(f"Invalid end byte: {frame[-1]:02X}")
	
	if len(frame) < 9:  # Minimum length: $ + 3 cmd + 4 crc + CR
		raise ValueError(f"Frame too short: {len(frame)} bytes")
	
	if not all(0x20 <= b <= 0x7E for b in frame[1:-1]):  # Check if all bytes in body are printable ASCII
		raise ValueError("Frame contains non-ASCII characters")
	
	if frame == b'$???,3278\r':
		raise ValueError("F70 returned error for invalid command")

	received_crc_hex = frame[-5:-1]
	try:
		received_crc = CRC16_ansi.from_hex(received_crc_hex.decode("ascii"))
	except ValueError:
		raise ValueError("Invalid CRC format")

	computed_crc = CRC16_ansi.from_data(frame[0:-5])
	if received_crc != computed_crc:
		raise ValueError(f"CRC mismatch: received {received_crc.hex}, computed {computed_crc.hex}")

	body = frame[1:-5]  # Command + Data
	command = F70Command(body[0:3].decode("ascii"))
	data_str = body[4:-1].decode("ascii")
	data_list = data_str.split(',') if data_str else []

	return F70Frame(command=command, data=tuple(data_list), crc=computed_crc)

def command_read_parse(ser: Serial, command: F70Command, data: str = "") -> F70Frame:
	frame = build_frame(command, data)
	ser.write(frame)

	# read while 0x0D not received, then parse frame
	response_bytes = ser.read_until(expected=b'\r', size=256)
	print(f"Received frame: {response_bytes}")

	if not response_bytes:
		raise TimeoutError("No response received")
	if not response_bytes.endswith(b'\r'):
		raise ValueError("Response does not end with CR")
	
	return parse_frame(response_bytes)
