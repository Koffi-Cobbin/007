"""
Tests for the agent state machine.
"""

import pytest

from agent_core.state_machine import NodeState, StateMachine


class TestStateMachine:
    def test_initial_state_is_offline(self):
        sm = StateMachine()
        assert sm.current == NodeState.OFFLINE
        assert sm.current_value == "offline"

    def test_transition_offline_to_enrolling(self):
        sm = StateMachine()
        sm.transition_to(NodeState.ENROLLING)
        assert sm.current == NodeState.ENROLLING

    def test_transition_enrolling_to_active(self):
        sm = StateMachine(NodeState.ENROLLING)
        sm.transition_to(NodeState.ACTIVE)
        assert sm.current == NodeState.ACTIVE

    def test_transition_active_to_idle(self):
        sm = StateMachine(NodeState.ACTIVE)
        sm.transition_to(NodeState.IDLE)
        assert sm.current == NodeState.IDLE

    def test_transition_idle_to_busy(self):
        sm = StateMachine(NodeState.IDLE)
        sm.transition_to(NodeState.BUSY)
        assert sm.current == NodeState.BUSY

    def test_transition_busy_to_idle(self):
        sm = StateMachine(NodeState.BUSY)
        sm.transition_to(NodeState.IDLE)
        assert sm.current == NodeState.IDLE

    def test_transition_any_to_offline(self):
        for state in NodeState:
            sm = StateMachine(state)
            if sm.can_transition_to(NodeState.OFFLINE):
                sm.transition_to(NodeState.OFFLINE)
                assert sm.current == NodeState.OFFLINE

    def test_transition_active_to_degraded(self):
        sm = StateMachine(NodeState.ACTIVE)
        sm.transition_to(NodeState.DEGRADED)
        assert sm.current == NodeState.DEGRADED

    def test_transition_degraded_to_active(self):
        sm = StateMachine(NodeState.DEGRADED)
        sm.transition_to(NodeState.ACTIVE)
        assert sm.current == NodeState.ACTIVE

    def test_invalid_transition_raises_error(self):
        sm = StateMachine(NodeState.OFFLINE)
        with pytest.raises(ValueError, match="Invalid transition"):
            sm.transition_to(NodeState.BUSY)

    def test_transition_to_same_state_is_noop(self):
        sm = StateMachine(NodeState.IDLE)
        sm.transition_to(NodeState.IDLE)
        assert sm.current == NodeState.IDLE

    def test_can_transition_to(self):
        sm = StateMachine(NodeState.OFFLINE)
        assert sm.can_transition_to(NodeState.ENROLLING)
        assert not sm.can_transition_to(NodeState.BUSY)

    def test_reset(self):
        sm = StateMachine(NodeState.BUSY)
        sm.reset()
        assert sm.current == NodeState.OFFLINE

    def test_repr(self):
        sm = StateMachine(NodeState.IDLE)
        assert repr(sm) == "StateMachine(idle)"

    def test_full_lifecycle(self):
        """Full agent lifecycle: offline → enrolling → active → idle → busy → idle."""
        sm = StateMachine()
        assert sm.current == NodeState.OFFLINE

        sm.transition_to(NodeState.ENROLLING)
        assert sm.current == NodeState.ENROLLING

        sm.transition_to(NodeState.ACTIVE)
        assert sm.current == NodeState.ACTIVE

        sm.transition_to(NodeState.IDLE)
        assert sm.current == NodeState.IDLE

        sm.transition_to(NodeState.BUSY)
        assert sm.current == NodeState.BUSY

        sm.transition_to(NodeState.IDLE)
        assert sm.current == NodeState.IDLE
