from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from f70_automate.domains.automation.monitoring import Condition, SampleWindow


@dataclass(frozen=True)
class ThresholdBelowCondition(Condition[float]):
    threshold: float
    cooldown_sec: float = 0.0
    required_sample_count: int = 1

    @property
    def window_size(self) -> int:
        if self.required_sample_count < 1:
            raise ValueError("required_sample_count must be >= 1")
        return self.required_sample_count

    def should_trigger(
        self,
        window: SampleWindow[float],
        occurred_at: datetime,
        last_trigger_time: datetime | None,
    ) -> bool:
        in_cooldown = (
            last_trigger_time is not None
            and (occurred_at - last_trigger_time).total_seconds() < self.cooldown_sec
        )
        if in_cooldown or len(window.values) < self.window_size:
            return False
        return all(sample < self.threshold for sample in window.values[-self.window_size :])
