from dataclasses import dataclass
from enum import StrEnum
import time
from typing import Optional


from f70_automate.apps.controller.protocols import ServiceRepository
from f70_automate.domains.automation.adapters.f70 import OperationTrigger
from f70_automate.domains.automation.adapters.wavelogger import ChannelValueStream
from f70_automate.domains.automation.conditions import ThresholdBelowCondition
from f70_automate.domains.automation.monitoring import MonitorSession, MonitorSpec, ThreadedMonitorRunner
from f70_automate.domains.automation.settings import AutomationSettings
from f70_automate.domains.f70_serial import f70_operation as f70_op
from f70_automate.domains.wavelogger.polling import WLXRuntime

@dataclass(frozen=True)
class AppConfiguration:
    port: str = "COM3"
    baudrate: int = 9600
    is_mock: bool = False


@dataclass
class AppState:
    automation_settings: AutomationSettings
    f70_connected: bool = False
    wave_running: bool = False
    last_error: str | None = None
    blocked_reason: str | None = None
    monitor_runner: Optional["ThreadedMonitorRunner"] = None
    current_configuration: Optional[AppConfiguration] = None

class ResultLevel(StrEnum):
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"

@dataclass
class Result[T = None]:
    level: ResultLevel
    message: Optional[str] = None
    payload: Optional[T] = None
    exception: Optional[Exception] = None
    
    @classmethod
    def success(cls, payload: Optional[T] = None, message: Optional[str] = None) -> Result[T]:
        return cls(level=ResultLevel.SUCCESS, message=message, payload=payload)
    @classmethod
    def warning(cls, message: str, payload: Optional[T] = None) -> Result[T]:
        return cls(level=ResultLevel.WARNING, message=message, payload=payload)
    @classmethod
    def error(cls, message: str, payload: Optional[T] = None, exception: Optional[Exception] = None) -> Result[T]:
        return cls(level=ResultLevel.ERROR, message=message, payload=payload, exception=exception)

class AutomationController:
    def __init__(self, repo: ServiceRepository):
        self._repo = repo

    # -------------------------
    # F70
    # -------------------------
    def reconnect_f70(self, state: AppState, conf: AppConfiguration) -> Result:
        self._stop_monitor(state)

        self._repo.reset_serial(conf.port, conf.baudrate, conf.is_mock)

        try:
            service = self._repo.get_serial(conf.port, conf.baudrate, conf.is_mock)
            service.call(f70_op.read_status)

            state.f70_connected = True
            state.last_error = None
            state.blocked_reason = None

            return Result.success(message="F70 reconnected successfully.")

        except Exception as exc:
            state.f70_connected = False
            state.last_error = f"F70 reconnect failed: {exc}"
            state.blocked_reason = "F70 is disconnected."

            return Result.error(message="F70 reconnect failed.", exception=exc)
        
    # -------------------------
    # WaveLogger
    # -------------------------
    def start_wave_acquisition(self, state: AppState, use_mock: bool) -> Result:
        self._stop_monitor(state)

        self._repo.reset_runtime(use_mock)

        try:
            runtime = self._repo.get_runtime(use_mock)
            runtime.runner.start()

            # 初期データ待ち
            while (
                runtime.store.get_current_physical(state.automation_settings.selected_channel) is None
                and runtime.runner.is_alive()
            ):
                time.sleep(0.1)

            runtime.store.check_exception()

            state.wave_running = True
            state.last_error = None
            state.blocked_reason = None

            return Result.success(message="WaveLogger acquisition started successfully.")

        except Exception as exc:
            state.wave_running = False
            state.last_error = f"WaveLogger start failed: {exc}"
            state.blocked_reason = "WaveLogger acquisition failed."
            
            return Result.error(message="WaveLogger start failed.", exception=exc)

    def stop_wave_acquisition(self, state: AppState, use_mock: bool):
        self._repo.reset_runtime(use_mock)
        state.wave_running = False

    # -------------------------
    # Automation
    # -------------------------
    def start_automation(
        self,
        state: AppState,
        conf: AppConfiguration,
        operation: f70_op.F70Operation,
        max_trigger_count: Optional[int] = 1,
    ) -> Result:
        if not state.f70_connected:
            state.blocked_reason = "Reconnect F70 first."
            return Result.error(message="F70 is not connected.")

        if not state.wave_running:
            state.blocked_reason = "Start WaveLogger first."
            return Result.error(message="WaveLogger acquisition is not running.")

        service = self._repo.get_serial(conf.port, conf.baudrate, conf.is_mock)
        runtime = self._repo.get_runtime(conf.is_mock)

        spec = MonitorSpec(
            condition=ThresholdBelowCondition(
                threshold=float(state.automation_settings.threshold),
                cooldown_sec=float(state.automation_settings.cooldown_sec),
                required_sample_count=int(state.automation_settings.required_sample_count),
            ),
            trigger=OperationTrigger(
                service=service,
                operation=operation,
            ),
            max_trigger_count=max_trigger_count,
        )

        session = MonitorSession(spec=spec)

        runner = ThreadedMonitorRunner(
            stream=ChannelValueStream(
                logger=runtime.publisher,
                channel=state.automation_settings.selected_channel,
            ),
            session=session,
        )

        runner.start()

        state.monitor_runner = runner
        state.blocked_reason = None

        return Result.success(message="Automation started successfully.")

    def stop_automation(self, state: AppState):
        self._stop_monitor(state)

    # -------------------------
    # Config変更
    # -------------------------
    def adapt_config(
        self,
        state: AppState,
        conf: AppConfiguration,
    ) -> Result:
        if state.current_configuration == conf:
            return Result.success(message="No configuration change needed.")

        try:
            self._stop_all(state)
            self._repo.reset_serial(conf.port, conf.baudrate, conf.is_mock)
            self._repo.reset_runtime(conf.is_mock)


        except Exception as exc:
            return Result.error(message="Failed to update configuration.", exception=exc)

        state.f70_connected = False
        state.wave_running = False
        state.current_configuration = conf
        
        return Result.success(message="Configuration updated successfully.")


    # -------------------------
    # internal
    # -------------------------
    def _stop_monitor(self, state: AppState):
        if state.monitor_runner:
            state.monitor_runner.stop()
            state.monitor_runner = None

    def _stop_all(self, state: AppState):
        self._stop_monitor(state)