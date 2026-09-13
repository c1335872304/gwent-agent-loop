"""Small, model-free state machine for Agent Loop task lifecycle."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .errors import StateTransitionError

STATES = frozenset(
    {
        "RECEIVED",
        "TRIAGED",
        "CONTEXTUALIZED",
        "PLANNED",
        "ASSIGNED",
        "IMPLEMENTING",
        "REVIEWING",
        "TESTING",
        "COMPLETED",
        "BLOCKED",
        "HUMAN_REQUIRED",
        "CANCELLED",
        "SUPERSEDED",
    }
)
TERMINAL_STATES = frozenset({"COMPLETED", "CANCELLED", "SUPERSEDED"})

_LINEAR = {
    "RECEIVED": "TRIAGED",
    "TRIAGED": "CONTEXTUALIZED",
    "CONTEXTUALIZED": "PLANNED",
    "PLANNED": "ASSIGNED",
    "ASSIGNED": "IMPLEMENTING",
    "IMPLEMENTING": "REVIEWING",
    "REVIEWING": "TESTING",
    "TESTING": "COMPLETED",
}


def validate_transition(current: str, target: str) -> None:
    """Reject every transition not explicitly present in the protocol."""
    if current not in STATES or target not in STATES:
        raise StateTransitionError(f"unknown state transition: {current!r} -> {target!r}")
    if current in TERMINAL_STATES:
        raise StateTransitionError(f"terminal state cannot transition: {current} -> {target}")
    if target in {"BLOCKED", "HUMAN_REQUIRED", "CANCELLED", "SUPERSEDED"}:
        return
    if current in {"REVIEWING", "TESTING"} and target == "TRIAGED":
        return
    if _LINEAR.get(current) == target:
        return
    raise StateTransitionError(f"illegal state transition: {current} -> {target}")


def apply_event(
    state: Mapping[str, Any],
    event: Mapping[str, Any],
    *,
    expected_task_revision: int,
) -> dict[str, Any]:
    """Apply one event, or return the unchanged state when the event is replayed.

    The caller persists the returned projection and the immutable event separately.
    A stale event sequence or task revision is rejected before any mutation.
    """
    required = {"event_id", "event_seq", "from_status", "to_status", "task_revision"}
    missing = sorted(required - set(event))
    if missing:
        raise StateTransitionError("event missing fields: " + ", ".join(missing))
    if int(event["task_revision"]) != expected_task_revision:
        raise StateTransitionError("event task revision does not match active packet")

    current = str(state.get("state", ""))
    event_id = str(event["event_id"])
    event_ids = [str(value) for value in state.get("event_ids", [])]
    if event_id in event_ids:
        result = deepcopy(dict(state))
        result["idempotent_replay"] = True
        return result

    expected_seq = int(state.get("event_seq", 0)) + 1
    if int(event["event_seq"]) != expected_seq:
        raise StateTransitionError(
            f"event sequence mismatch: expected {expected_seq}, got {event['event_seq']}"
        )
    if str(event["from_status"]) != current:
        raise StateTransitionError(
            f"event starts at {event['from_status']!r}, projection is {current!r}"
        )

    target = str(event["to_status"])
    validate_transition(current, target)
    result = deepcopy(dict(state))
    result.update(
        {
            "state": target,
            "event_seq": expected_seq,
            "task_revision": expected_task_revision,
            "event_ids": event_ids + [event_id],
            "idempotent_replay": False,
        }
    )
    return result
