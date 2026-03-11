from dataclasses import dataclass

import f70_automate.domains.f70_serial.f70_serial as f70
from f70_automate.tests.mock.fake_serial import Responder


@dataclass
class F70Responder(Responder):
    system_on: bool = False
    coldhead_running: bool = False
    temperatures: tuple[float, float, float, float] = (20.0, 21.0, 22.0, 23.0)
    pressures: tuple[float, float] = (1.0, 0.9)
    version: str = "FAKE-1.0"
    elapsed_hours: float = 0.0
    alarm_mask: int = 0

    def __call__(self, request: bytes) -> bytes:
        response = self._responce(f70.parse_frame(request))
        # command_read_parse() expects a frame terminated by CR.
        return response.as_bytes() + b"\r"

    def _build_response(self, command: f70.F70Command, data: tuple[str, ...]) -> f70.F70Frame:
        payload = f"${command.value},{','.join(data)},"
        crc = f70.CRC16_ansi.from_data(payload.encode("ascii"))
        return f70.F70Frame(command=command, data=data, crc=crc)

    def _status_hex(self) -> str:
        state = f70.F70StateNumber.ColdHeadRun if self.coldhead_running else (
            f70.F70StateNumber.RemoteOn if self.system_on else f70.F70StateNumber.LocalOff
        )
        value = self.alarm_mask & 0x01FE
        value |= (int(state) & 0b111) << 9
        if self.system_on:
            value |= 0b1
        return f"{value:04X}"

    def _responce(self, request: f70.F70Frame) -> f70.F70Frame:
        command = request.command
        match command:
            case f70.F70Command.ReadAllTemps:
                data = tuple(f"{t:.1f}" for t in self.temperatures)
                return self._build_response(command, data)
            case f70.F70Command.ReadTemp1:
                return self._build_response(command, (f"{self.temperatures[0]:.1f}",))
            case f70.F70Command.ReadTemp2:
                return self._build_response(command, (f"{self.temperatures[1]:.1f}",))
            case f70.F70Command.ReadTemp3:
                return self._build_response(command, (f"{self.temperatures[2]:.1f}",))
            case f70.F70Command.ReadTemp4:
                return self._build_response(command, (f"{self.temperatures[3]:.1f}",))
            case f70.F70Command.ReadAllPressures:
                data = tuple(f"{p:.2f}" for p in self.pressures)
                return self._build_response(command, data)
            case f70.F70Command.ReadPressure1:
                return self._build_response(command, (f"{self.pressures[0]:.2f}",))
            case f70.F70Command.ReadPressure2:
                return self._build_response(command, (f"{self.pressures[1]:.2f}",))
            case f70.F70Command.ReadStatesBits:
                return self._build_response(command, (self._status_hex(),))
            case f70.F70Command.ReadVersionAndElapsedHour:
                return self._build_response(command, (self.version, f"{self.elapsed_hours:.1f}"))
            case f70.F70Command.PowerOn:
                self.system_on = True
                return self._build_response(command, tuple())
            case f70.F70Command.PowerOff:
                self.system_on = False
                self.coldhead_running = False
                return self._build_response(command, tuple())
            case f70.F70Command.ColdHeadRun:
                if not self.system_on:
                    raise RuntimeError("Cannot run coldhead while system is off.")
                self.coldhead_running = True
                return self._build_response(command, tuple())
            case f70.F70Command.ColdHeadPause:
                self.coldhead_running = False
                return self._build_response(command, tuple())
            case f70.F70Command.Reset:
                self.alarm_mask = 0
                return self._build_response(command, tuple())
            case _:
                raise ValueError(f"Unsupported command: {command}")
