"""
Tests for the agent scheduler.
"""

import time
from unittest.mock import MagicMock, PropertyMock

import pytest

from agent_core.scheduler import AgentScheduler
from agent_core.state_machine import NodeState, StateMachine


class _MockHttpResponse:
    def __init__(self, status_code, data=None):
        self.status_code = status_code
        self.data = data or {}

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    @property
    def no_content(self):
        return self.status_code == 204


def _make_mock_http():
    http = MagicMock()
    http.send_heartbeat = MagicMock(return_value=_MockHttpResponse(200, {"accepted": True}))
    http.poll_task = MagicMock(return_value=_MockHttpResponse(204))
    http.submit_result = MagicMock(return_value=_MockHttpResponse(200, {"accepted": True}))
    return http


class TestAgentScheduler:
    def test_start_stops_cleanly(self):
        http = _make_mock_http()
        sm = StateMachine(NodeState.IDLE)
        scheduler = AgentScheduler(http=http, state_machine=sm, node_id="n-1", heartbeat_interval=999, task_poll_interval=999)

        scheduler.start()
        assert scheduler._running is True
        assert scheduler._start_time > 0

        scheduler.stop()
        assert scheduler._running is False

    def test_heartbeat_sends_status(self):
        http = _make_mock_http()
        sm = StateMachine(NodeState.IDLE)
        scheduler = AgentScheduler(http=http, state_machine=sm, node_id="n-1", heartbeat_interval=0.05, task_poll_interval=999)

        scheduler.start()
        time.sleep(0.12)
        scheduler.stop()

        assert http.send_heartbeat.called
        # Check that the heartbeat was called with idle status
        call_args = http.send_heartbeat.call_args
        assert call_args is not None
        assert call_args.kwargs.get("status") == "idle" or call_args[0][2] == "idle"

    def test_task_poll_called(self):
        http = _make_mock_http()
        sm = StateMachine(NodeState.IDLE)
        scheduler = AgentScheduler(http=http, state_machine=sm, node_id="n-1", heartbeat_interval=999, task_poll_interval=0.05)

        scheduler.start()
        time.sleep(0.12)
        scheduler.stop()

        assert http.poll_task.called

    def test_task_received_calls_callback(self):
        http = _make_mock_http()
        # Make poll return a task
        http.poll_task = MagicMock(return_value=_MockHttpResponse(200, {
            "task_id": "t-1",
            "job_id": "j-1",
            "task_type": "checksum",
            "payload": {"files": ["a.txt"]},
            "deadline_seconds": 300,
        }))

        callback = MagicMock()
        sm = StateMachine(NodeState.IDLE)
        scheduler = AgentScheduler(
            http=http, state_machine=sm, node_id="n-1",
            heartbeat_interval=999, task_poll_interval=0.05,
            on_task_received=callback,
        )

        scheduler.start()
        time.sleep(0.12)
        scheduler.stop()

        assert callback.called
        assert callback.call_args[0][0]["task_id"] == "t-1"

    def test_task_received_changes_state_to_busy(self):
        http = _make_mock_http()
        http.poll_task = MagicMock(return_value=_MockHttpResponse(200, {
            "task_id": "t-1",
            "task_type": "checksum",
            "payload": {},
            "deadline_seconds": 300,
        }))

        sm = StateMachine(NodeState.IDLE)
        scheduler = AgentScheduler(
            http=http, state_machine=sm, node_id="n-1",
            heartbeat_interval=999, task_poll_interval=0.05,
        )

        scheduler.start()
        time.sleep(0.12)
        scheduler.stop()

        assert sm.current == NodeState.BUSY

    def test_on_task_completed_returns_to_idle(self):
        sm = StateMachine(NodeState.BUSY)
        http = _make_mock_http()
        scheduler = AgentScheduler(http=http, state_machine=sm, node_id="n-1")

        scheduler.on_task_completed()
        assert sm.current == NodeState.IDLE

    def test_on_degraded(self):
        sm = StateMachine(NodeState.ACTIVE)
        http = _make_mock_http()
        scheduler = AgentScheduler(http=http, state_machine=sm, node_id="n-1")

        scheduler.on_degraded()
        assert sm.current == NodeState.DEGRADED
