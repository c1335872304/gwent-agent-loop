"""Whole-task model and execution budget accounting."""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import BudgetExceeded


@dataclass(frozen=True)
class BudgetLimits:
    max_role_runs: int
    max_subtasks: int
    max_subtask_depth: int
    max_input_tokens: int
    max_output_tokens: int
    max_model_turns: int
    max_elapsed_minutes: int


@dataclass
class BudgetUsage:
    role_runs: int = 0
    subtasks: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model_turns: int = 0
    elapsed_minutes: int = 0


@dataclass
class BudgetLedger:
    limits: BudgetLimits
    usage: BudgetUsage = field(default_factory=BudgetUsage)

    def reserve(
        self,
        *,
        role_runs: int = 0,
        subtasks: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model_turns: int = 0,
        elapsed_minutes: int = 0,
    ) -> None:
        increments = {
            "role_runs": role_runs,
            "subtasks": subtasks,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model_turns": model_turns,
            "elapsed_minutes": elapsed_minutes,
        }
        if any(value < 0 for value in increments.values()):
            raise BudgetExceeded("budget reservations cannot be negative")
        projected = {
            name: getattr(self.usage, name) + value for name, value in increments.items()
        }
        caps = {
            "role_runs": self.limits.max_role_runs,
            "subtasks": self.limits.max_subtasks,
            "input_tokens": self.limits.max_input_tokens,
            "output_tokens": self.limits.max_output_tokens,
            "model_turns": self.limits.max_model_turns,
            "elapsed_minutes": self.limits.max_elapsed_minutes,
        }
        exceeded = [name for name, value in projected.items() if value > caps[name]]
        if exceeded:
            details = ", ".join(
                f"{name}={projected[name]}/{caps[name]}" for name in exceeded
            )
            raise BudgetExceeded("reservation exceeds whole-task budget: " + details)
        for name, value in increments.items():
            setattr(self.usage, name, getattr(self.usage, name) + value)

    def ratios(self) -> dict[str, float]:
        caps = {
            "role_runs": self.limits.max_role_runs,
            "subtasks": self.limits.max_subtasks,
            "input_tokens": self.limits.max_input_tokens,
            "output_tokens": self.limits.max_output_tokens,
            "model_turns": self.limits.max_model_turns,
            "elapsed_minutes": self.limits.max_elapsed_minutes,
        }
        return {
            name: (getattr(self.usage, name) / cap if cap else 1.0)
            for name, cap in caps.items()
        }

    def warnings(self, threshold: float = 0.8) -> list[str]:
        return [name for name, ratio in self.ratios().items() if ratio >= threshold]

    @property
    def exhausted(self) -> bool:
        return bool(self.warnings(threshold=1.0))
