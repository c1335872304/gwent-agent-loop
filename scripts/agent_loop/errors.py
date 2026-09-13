"""Errors raised when an Agent Loop protocol guard rejects an operation."""


class AgentLoopError(ValueError):
    """Base class for deterministic protocol failures."""


class ValidationError(AgentLoopError):
    """An input artifact does not satisfy its protocol contract."""


class StateTransitionError(AgentLoopError):
    """A state event is illegal, stale, or not idempotent."""


class BudgetExceeded(AgentLoopError):
    """A whole-task execution budget would be exceeded."""


class LockConflict(AgentLoopError):
    """A requested write or contract lock overlaps another owner."""


class SnapshotDrift(AgentLoopError):
    """The workspace no longer matches the snapshot used by an artifact."""
