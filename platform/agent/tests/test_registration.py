"""
Tests for the registration flow.

Uses monkeypatching to avoid real HTTP calls.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

import pytest

from agent_core.registration import RegistrationError, RegistrationFlow
from agent_core.state_machine import NodeState, StateMachine


class _MockHttpResponse:
    """Simulates transport.HttpResponse."""
    def __init__(self, status_code, data=None):
        self.status_code = status_code
        self.data = data
        self._ok = 200 <= status_code < 300

    @property
    def ok(self):
        return self._ok


def _make_mock_http(register_resp=None, activate_resp=None):
    http = MagicMock()
    http.register = MagicMock(return_value=register_resp or _MockHttpResponse(201, {
        "node_id": "n-123",
        "status": "enrolled",
        "token": "tok-abc",
        "heartbeat_interval_seconds": 30,
    }))
    http.activate = MagicMock(return_value=activate_resp or _MockHttpResponse(200, {
        "node_id": "n-123",
        "status": "active",
    }))
    http.base_url = "http://test:8000"
    return http


class TestRegistrationFlow:
    def test_register_success(self, tmp_path):
        http = _make_mock_http()
        sm = StateMachine()
        flow = RegistrationFlow(
            http=http,
            state_machine=sm,
            device_id="device-1",
            enrollment_key="key-1",
            capabilities={"cpu_cores": 8},
            token_path=tmp_path / "token.json",
        )

        result = flow.register()
        assert result is True
        assert flow.node_id == "n-123"
        assert flow.token == "tok-abc"
        assert sm.current == NodeState.ACTIVE

        # Check token was persisted
        assert (tmp_path / "token.json").exists()
        with open(tmp_path / "token.json") as f:
            data = json.load(f)
        assert data["device_id"] == "device-1"
        assert data["node_id"] == "n-123"
        assert data["token"] == "tok-abc"

    def test_register_persists_and_reuses_token(self, tmp_path):
        http = _make_mock_http()
        sm = StateMachine()

        # First registration
        flow1 = RegistrationFlow(
            http=http,
            state_machine=sm,
            device_id="device-1",
            enrollment_key="key-1",
            capabilities={},
            token_path=tmp_path / "token.json",
        )
        flow1.register()

        # Second registration — should reuse stored token
        http2 = MagicMock()  # no register/activate mocked — should not be called
        sm2 = StateMachine()
        flow2 = RegistrationFlow(
            http=http2,
            state_machine=sm2,
            device_id="device-1",
            enrollment_key="key-1",
            capabilities={},
            token_path=tmp_path / "token.json",
        )
        result = flow2.register()
        assert result is True
        assert flow2.node_id == "n-123"
        assert flow2.token == "tok-abc"
        assert sm2.current == NodeState.ACTIVE  # directly, via stored identity
        http2.register.assert_not_called()

    def test_register_invalid_enrollment_key(self, tmp_path):
        http = _make_mock_http(
            register_resp=_MockHttpResponse(401, {"error": {"code": "INVALID_ENROLLMENT_KEY"}}),
        )
        sm = StateMachine()
        flow = RegistrationFlow(
            http=http,
            state_machine=sm,
            device_id="device-1",
            enrollment_key="bad-key",
            capabilities={},
            token_path=tmp_path / "token.json",
        )

        with pytest.raises(RegistrationError, match="Invalid or inactive"):
            flow.register()
        assert sm.current == NodeState.OFFLINE

    def test_register_bad_request(self, tmp_path):
        http = _make_mock_http(
            register_resp=_MockHttpResponse(400, {"device_id": ["already exists"]}),
        )
        sm = StateMachine()
        flow = RegistrationFlow(
            http=http,
            state_machine=sm,
            device_id="dup-device",
            enrollment_key="key-1",
            capabilities={},
            token_path=tmp_path / "token.json",
        )

        with pytest.raises(RegistrationError, match="Registration rejected"):
            flow.register()
        assert sm.current == NodeState.OFFLINE

    def test_force_re_register(self, tmp_path):
        http = _make_mock_http()
        sm = StateMachine()

        flow = RegistrationFlow(
            http=http,
            state_machine=sm,
            device_id="device-1",
            enrollment_key="key-1",
            capabilities={},
            token_path=tmp_path / "token.json",
        )
        flow.register()

        # Force re-registration
        flow.re_register()
        # register() would be called again (2nd time since stored identity is ignored)
        assert http.register.call_count == 2

    def test_stored_token_wrong_device_id(self, tmp_path):
        """If stored token has different device_id, re-register."""
        # Create token file with mismatched device
        token_path = tmp_path / "token.json"
        with open(token_path, "w") as f:
            json.dump({"device_id": "other-device", "node_id": "n-999", "token": "tok-999"}, f)

        http = _make_mock_http()
        sm = StateMachine()
        flow = RegistrationFlow(
            http=http,
            state_machine=sm,
            device_id="device-1",
            enrollment_key="key-1",
            capabilities={},
            token_path=token_path,
        )
        flow.register()
        # Should have registered fresh
        assert flow.node_id == "n-123"
        assert http.register.called
