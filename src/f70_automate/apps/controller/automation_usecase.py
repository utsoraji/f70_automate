from dataclasses import dataclass
import time
from typing import Callable, Concatenate, ParamSpec, Protocol, TypeVar

from f70_automate._core.serial.serial_async import SerialPortLike
from f70_automate._core.serial.serial_service import CallableWithCanExecute
from f70_automate.domains.automation.adapters import ChannelValueStream, OperationTrigger
from f70_automate.domains.automation.conditions import ThresholdBelowCondition
from f70_automate.domains.automation.monitoring import (
    MonitorSession,
    MonitorSpec,
    MonitorSnapshot,
    ThreadedMonitorRunner,
)
from f70_automate.domains.automation.settings import AutomationSettings
from f70_automate.domains.f70_serial import f70_operation as f70_op
from f70_automate.domains.f70_serial import f70_serial as f70
from f70_automate.domains.f70_serial.f70_operation import F70Operation
from f70_automate.domains.wavelogger import ChannelConfig, WLXRuntime, read_channel_configs

P = ParamSpec("P")
R = TypeVar("R", covariant=True)


class SerialServiceLike(Protocol):
    @property
    def is_alive(self) -> bool: ...

    @property
    def closed(self) -> bool: ...

    def call(self, fn: Callable[Concatenate[SerialPortLike, P], R], *a: P.args, **kw: P.kwargs) -> R: ...

    __call__ = call

    def call_checked(self, operation: CallableWithCanExecute[P, R]) -> R: ...

    def shutdown(self) -> None: ...


@dataclass
class DashboardState:
    f70_connected: bool = False
    wave_running: bool = False
    last_error: str | None = None
    blocked_reason: str | None = None


def get_monitor_snapshot(monitor_runner: ThreadedMonitorRunner | None) -> MonitorSnapshot:
    if monitor_runner is None:
        return MonitorSnapshot(is_running=False)
    return monitor_runner.snapshot()


def format_trigger_result(result: object | None) -> str:
    if result is None:
        return "N/A"
    if isinstance(result, F70Operation):
        return result.name
    return str(result)


def format_monitor_error(error: Exception | None) -> str | None:
    if error is None:
        return None
    return str(error)


def automation_ready(dashboard_state: DashboardState) -> tuple[bool, str | None]:
    if not dashboard_state.f70_connected:
        return False, "Reconnect F70 first."
    if not dashboard_state.wave_running:
        return False, "Start WaveLogger acquisition first."
    return True, None


def load_automation_channels(channel_config_path: str) -> tuple[ChannelConfig, ...]:
    channels = read_channel_configs(channel_config_path)
    if not channels:
        raise ValueError("At least one WaveLogger channel must be configured.")
    return channels


def get_automation_operations() -> tuple[F70Operation, ...]:
    return (
        f70_op.no_op,
        f70_op.power_on,
        f70_op.power_off,
        f70_op.coldhead_run,
        f70_op.coldhead_pause,
        f70_op.reset,
    )


def get_active_alarm_names(status: f70.F70StatusBits) -> tuple[str, ...]:
    alarms: list[str] = []
    if status.pressure_alarm:
        alarms.append("Pressure")
    if status.oil_alarm:
        alarms.append("Oil")
    if status.water_flow_alarm:
        alarms.append("Water Flow")
    if status.water_temp_alarm:
        alarms.append("Water Temp")
    if status.helium_temp_alarm:
        alarms.append("Helium Temp")
    if status.phase_alarm:
        alarms.append("Phase/Fuse")
    if status.motor_temp_alarm:
        alarms.append("Motor Temp")
    return tuple(alarms)


def build_monitor_runner(
    *,
    runtime: WLXRuntime,
    service: SerialServiceLike,
    settings: AutomationSettings,
    operation: F70Operation,
) -> ThreadedMonitorRunner:
    spec = MonitorSpec(
        condition=ThresholdBelowCondition(
            threshold=float(settings.threshold),
            cooldown_sec=float(settings.cooldown_sec),
            required_sample_count=int(settings.required_sample_count),
        ),
        trigger=OperationTrigger(
            service=service,
            operation=operation,
        ),
        max_trigger_count=1,
    )
    session = MonitorSession(spec=spec)
    return ThreadedMonitorRunner(
        stream=ChannelValueStream(
            logger=runtime.publisher,
            channel=settings.selected_channel,
        ),
        session=session,
    )


def read_f70_status(service: SerialServiceLike):
    return service.call(f70_op.read_status)


def stop_wave_logger(runtime: WLXRuntime, monitor_runner: ThreadedMonitorRunner | None = None) -> None:
    if monitor_runner is not None:
        monitor_runner.stop()
    if runtime.runner.is_alive():
        runtime.runner.stop()
        runtime.runner.join(timeout=1.0)


def stop_monitor_runner(monitor_runner: ThreadedMonitorRunner | None = None) -> None:
    if monitor_runner is not None:
        monitor_runner.stop()


def reset_serial_service(
    resolve_service: Callable[[], SerialServiceLike],
    clear_service_cache: Callable[[], None],
) -> None:
    try:
        service = resolve_service()
        service.shutdown()
    except Exception:
        pass
    clear_service_cache()


def reset_wave_logger(
    resolve_runtime: Callable[[], WLXRuntime],
    clear_runtime_cache: Callable[[], None],
    monitor_runner: ThreadedMonitorRunner | None = None,
) -> None:
    try:
        runtime = resolve_runtime()
        stop_wave_logger(runtime, monitor_runner)
    except Exception:
        pass
    clear_runtime_cache()


def reconnect_f70(
    dashboard_state: DashboardState,
    resolve_service: Callable[[], SerialServiceLike],
    clear_service_cache: Callable[[], None],
    monitor_runner: ThreadedMonitorRunner | None = None,
) -> SerialServiceLike | None:
    if monitor_runner is not None:
        monitor_runner.stop()
    reset_serial_service(resolve_service, clear_service_cache)
    try:
        service = resolve_service()
        read_f70_status(service)
        dashboard_state.f70_connected = True
        dashboard_state.last_error = None
        dashboard_state.blocked_reason = None
        return service
    except Exception as exc:
        dashboard_state.f70_connected = False
        dashboard_state.last_error = f"F70 reconnect failed: {exc}"
        dashboard_state.blocked_reason = "F70 is disconnected."
        return None


def start_wave_acquisition(
    dashboard_state: DashboardState,
    settings: AutomationSettings,
    resolve_runtime: Callable[[], WLXRuntime],
    clear_runtime_cache: Callable[[], None],
    monitor_runner: ThreadedMonitorRunner | None = None,
) -> WLXRuntime | None:
    reset_wave_logger(resolve_runtime, clear_runtime_cache, monitor_runner)
    try:
        runtime = resolve_runtime()
        runtime.runner.start()
        while runtime.store.get_current_physical(settings.selected_channel) is None and runtime.runner.is_alive():
            time.sleep(0.1)
        runtime.store.check_exception()
        dashboard_state.wave_running = True
        dashboard_state.last_error = None
        dashboard_state.blocked_reason = None
        return runtime
    except Exception as exc:
        dashboard_state.wave_running = False
        dashboard_state.last_error = f"WaveLogger start failed: {exc}"
        dashboard_state.blocked_reason = "WaveLogger acquisition failed."
        return None


def stop_wave_acquisition(
    dashboard_state: DashboardState,
    resolve_runtime: Callable[[], WLXRuntime],
    clear_runtime_cache: Callable[[], None],
    monitor_runner: ThreadedMonitorRunner | None = None,
) -> None:
    reset_wave_logger(resolve_runtime, clear_runtime_cache, monitor_runner)
    dashboard_state.wave_running = False


def action_mode_changed(
    state: DashboardState,
    resolve_stale_service: Callable[[], SerialServiceLike],
    clear_service_cache: Callable[[], None],
    resolve_stale_runtime: Callable[[], WLXRuntime],
    clear_runtime_cache: Callable[[], None],
    monitor_runner: ThreadedMonitorRunner | None,
) -> None:
    """モード切り替え時にリソースを停止・破棄し状態をリセットする。"""
    stop_monitor_runner(monitor_runner)
    reset_serial_service(resolve_stale_service, clear_service_cache)
    reset_wave_logger(resolve_stale_runtime, clear_runtime_cache)
    state.f70_connected = False
    state.wave_running = False


def action_toggle_wave(
    state: DashboardState,
    settings: AutomationSettings,
    resolve_runtime: Callable[[], WLXRuntime],
    clear_runtime_cache: Callable[[], None],
    monitor_runner: ThreadedMonitorRunner | None,
) -> WLXRuntime | None:
    """WaveLogger の取得開始／停止を切り替える。停止時は None を返す。"""
    stop_monitor_runner(monitor_runner)
    if state.wave_running:
        stop_wave_acquisition(
            dashboard_state=state,
            resolve_runtime=resolve_runtime,
            clear_runtime_cache=clear_runtime_cache,
        )
        return None
    return start_wave_acquisition(
        dashboard_state=state,
        settings=settings,
        resolve_runtime=resolve_runtime,
        clear_runtime_cache=clear_runtime_cache,
    )


def action_toggle_automation(
    state: DashboardState,
    monitor_runner: ThreadedMonitorRunner | None,
    service: SerialServiceLike | None,
    runtime: WLXRuntime | None,
    settings: AutomationSettings,
    operation: F70Operation,
) -> ThreadedMonitorRunner | None:
    """オートメーションの ON/OFF を切り替える。
    - 実行中の場合は停止して None を返す。
    - 未準備の場合は blocked_reason を設定して None を返す。
    - 準備完了の場合は新しい runner を起動して返す。
    """
    if monitor_runner is not None and monitor_runner.snapshot().is_running:
        monitor_runner.stop()
        return None
    if service is None or runtime is None:
        state.blocked_reason = "Reconnect F70 and start WaveLogger acquisition first."
        return None
    runner = build_monitor_runner(
        runtime=runtime,
        service=service,
        settings=settings,
        operation=operation,
    )
    runner.start()
    return runner
