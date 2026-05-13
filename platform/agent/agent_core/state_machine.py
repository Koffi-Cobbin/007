"""
Node state machine.

Tracks and validates transitions between agent states matching the backend's
node state machine defined in PROTOCOL.md.
"""

from enum import Enum, auto


class NodeState(Enum):
    OFFLINE = "offline"
    ENROLLING = "enrolling"
    ACTIVE = "active"
    IDLE = "idle"
    BUSY = "busy"
    DEGRADED = "degraded"

    def __str__(self):
        return self.value


# ── Valid transitions ──────────────────────────────────────────────
# Maps each state → set of allowed next states.

_TRANSITIONS = {
    NodeState.OFFLINE:    {NodeState.ENROLLING},
    NodeState.ENROLLING:  {NodeState.ACTIVE, NodeState.OFFLINE},
    NodeState.ACTIVE:     {NodeState.IDLE, NodeState.DEGRADED, NodeState.OFFLINE},
    NodeState.IDLE:       {NodeState.BUSY, NodeState.DEGRADED, NodeState.OFFLINE, NodeState.ACTIVE},
    NodeState.BUSY:       {NodeState.IDLE, NodeState.DEGRADED, NodeState.OFFLINE},
    NodeState.DEGRADED:   {NodeState.ACTIVE, NodeState.OFFLINE},
}


class StateMachine:
    """Lightweight state machine for node lifecycle management."""

    def __init__(self, initial: NodeState = NodeState.OFFLINE):
        self._current = initial

    @property
    def current(self) -> NodeState:
        return self._current

    @property
    def current_value(self) -> str:
        return self._current.value

    def can_transition_to(self, target: NodeState) -> bool:
        return target in _TRANSITIONS.get(self._current, set())

    def transition_to(self, target: NodeState) -> NodeState:
        """Attempt a state transition. Raises ValueError if invalid."""
        if target == self._current:
            return self._current
        if not self.can_transition_to(target):
            raise ValueError(
                f"Invalid transition: {self._current.value} → {target.value}. "
                f"Allowed: {[s.value for s in _TRANSITIONS.get(self._current, set())]}"
            )
        self._current = target
        return self._current

    def reset(self):
        """Reset to offline (e.g. after unrecoverable error)."""
        self._current = NodeState.OFFLINE

    def __repr__(self):
        return f"StateMachine({self._current.value})"


# ── Convenience guard ──────────────────────────────────────────────

def require_state(*allowed_states: NodeState):
    """Decorator factory that checks the node is in one of the allowed states."""
    def decorator(method):
        def wrapper(self, *args, **kwargs):
            if self.state_machine.current not in allowed_states:
                raise RuntimeError(
                    f"Operation not allowed in state '{self.state_machine.current.value}'. "
                    f"Required: {[s.value for s in allowed_states]}"
                )
            return method(self, *args, **kwargs)
        return wrapper
    return decorator
