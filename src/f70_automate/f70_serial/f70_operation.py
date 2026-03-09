from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from serial import Serial

from f70_automate.f70_serial import f70_serial as f70


CheckPredicate = Callable[[f70.F70StatusBits], bool]


class CheckCommand(Enum):
    NONE = "none"
    STATUS = "status"


@dataclass(frozen=True)
class F70Operation:
    name: str
    execute: Callable[..., Any]
    mutates_state: bool
    check_command: CheckCommand = CheckCommand.NONE
    check_predicate: CheckPredicate | None = None

    def __call__(self, ser: Serial, *args: Any, **kwargs: Any) -> Any:
        return self.execute(ser, *args, **kwargs)

    def can_execute(self, ser: Serial) -> bool:
        if self.check_command is CheckCommand.NONE:
            return True
        if self.check_command is CheckCommand.STATUS:
            status = _read_status_impl(ser)
            if self.check_predicate is None:
                return True
            return self.check_predicate(status)
        raise ValueError(f"Unsupported check_command: {self.check_command}")

def _read_temperature_impl(ser: Serial, sensor_id: int) -> float:
    match sensor_id:
        case 1:
            command = f70.F70Command.ReadTemp1
        case 2:
            command = f70.F70Command.ReadTemp2
        case 3:
            command = f70.F70Command.ReadTemp3
        case 4:
            command = f70.F70Command.ReadTemp4
        case _:
            command = f70.F70Command.Invalid

    response = f70.command_read_parse(ser, command)
    if not response.data:
        raise ValueError("No temperature data in response")
    return float(response.data[0])


def _read_all_temperatures_impl(ser: Serial) -> list[float]:
    response = f70.command_read_parse(ser, f70.F70Command.ReadAllTemps)
    if not response.data:
        raise ValueError("No temperature data in response")
    return [float(x) for x in response.data]


def _read_pressure_impl(ser: Serial, sensor_id: int = 0) -> float:
    match sensor_id:
        case 1:
            command = f70.F70Command.ReadPressure1
        case 2:
            command = f70.F70Command.ReadPressure2
        case _:
            command = f70.F70Command.Invalid

    response = f70.command_read_parse(ser, command)
    if not response.data:
        raise ValueError("No pressure data in response")
    return float(response.data[0])


def _read_all_pressures_impl(ser: Serial) -> list[float]:
    response = f70.command_read_parse(ser, f70.F70Command.ReadAllPressures)
    if not response.data:
        raise ValueError("No pressure data in response")
    return [float(x) for x in response.data]


def _read_status_impl(ser: Serial) -> f70.F70StatusBits:
    response = f70.command_read_parse(ser, f70.F70Command.ReadStatesBits)
    if not response.data:
        raise ValueError("No status data in response")
    return f70.F70StatusBits(response.data[0])


def _read_version_impl(ser: Serial) -> f70.F70VersionAndElapsedHour:
    response = f70.command_read_parse(ser, f70.F70Command.ReadVersionAndElapsedHour)
    if not response.data:
        raise ValueError("No version data in response")
    return f70.F70VersionAndElapsedHour.from_data(response.data)


def _power_on_impl(ser: Serial) -> f70.F70Frame:
    return f70.command_read_parse(ser, f70.F70Command.PowerOn)


def _power_off_impl(ser: Serial) -> f70.F70Frame:
    return f70.command_read_parse(ser, f70.F70Command.PowerOff)


def _coldhead_run_impl(ser: Serial) -> f70.F70Frame:
    return f70.command_read_parse(ser, f70.F70Command.ColdHeadRun)


def _coldhead_pause_impl(ser: Serial) -> f70.F70Frame:
    return f70.command_read_parse(ser, f70.F70Command.ColdHeadPause)


def _reset_impl(ser: Serial) -> f70.F70Frame:
    return f70.command_read_parse(ser, f70.F70Command.Reset)


read_temperature = F70Operation(
    name="read_temperature",
    execute=_read_temperature_impl,
    mutates_state=False,
)

read_all_temperatures = F70Operation(
    name="read_all_temperatures",
    execute=_read_all_temperatures_impl,
    mutates_state=False,
)

read_pressure = F70Operation(
    name="read_pressure",
    execute=_read_pressure_impl,
    mutates_state=False,
)

read_all_pressures = F70Operation(
    name="read_all_pressures",
    execute=_read_all_pressures_impl,
    mutates_state=False,
)

read_status = F70Operation(
    name="read_status",
    execute=_read_status_impl,
    mutates_state=False,
)

read_version = F70Operation(
    name="read_version",
    execute=_read_version_impl,
    mutates_state=False,
)

send_command = F70Operation(
    name="send_command",
    execute=f70.command_read_parse,
    mutates_state=True,
)

power_on = F70Operation(
    name="power_on",
    execute=_power_on_impl,
    mutates_state=True,
    check_command=CheckCommand.STATUS,
    check_predicate=lambda status: status.state_number == f70.F70StateNumber.LocalOff and not status.alarms_active,
)

power_off = F70Operation(
    name="power_off",
    execute=_power_off_impl,
    mutates_state=True,
    check_command=CheckCommand.STATUS,
    check_predicate=lambda status: status.system_on,
)

coldhead_run = F70Operation(
    name="coldhead_run",
    execute=_coldhead_run_impl,
    mutates_state=True,
    check_command=CheckCommand.STATUS,
    check_predicate=lambda status: status.system_on and status.state_number != f70.F70StateNumber.ColdHeadRun,
)

coldhead_pause = F70Operation(
    name="coldhead_pause",
    execute=_coldhead_pause_impl,
    mutates_state=True,
    check_command=CheckCommand.STATUS,
    check_predicate=lambda status: status.state_number == f70.F70StateNumber.ColdHeadRun,
)

reset = F70Operation(
    name="reset",
    execute=_reset_impl,
    mutates_state=True,
    check_command=CheckCommand.STATUS,
)


OPERATIONS: dict[str, F70Operation] = {
    op.name: op
    for op in (
        read_temperature,
        read_all_temperatures,
        read_pressure,
        read_all_pressures,
        read_status,
        read_version,
        send_command,
        power_on,
        power_off,
        coldhead_run,
        coldhead_pause,
        reset,
    )
}


if __name__ == "__main__":
    ser = Serial("COM3", 9600, timeout=1)
    print(read_version(ser))
    print(read_status(ser))
