"""
Registration flow: enrolls the device with the backend and activates it.

Sequence:
  1. Check if we already have a stored node_id + token
  2. If not, POST /nodes/register/ with the enrollment key
  3. Store the returned node_id and token
  4. PUT /nodes/{id}/activate/ to mark the node ready
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from agent_core.state_machine import NodeState, StateMachine
from transport.http_client import HttpClient, TransportError, UnauthorizedError

logger = logging.getLogger(__name__)


class RegistrationError(Exception):
    """Raised when registration fails permanently."""


class RegistrationFlow:
    """Manages the device registration lifecycle."""

    def __init__(
        self,
        http: HttpClient,
        state_machine: StateMachine,
        device_id: str,
        enrollment_key: str,
        capabilities: dict,
        hostname: str = "",
        platform: str = "",
        agent_version: str = "1.0.0",
        token_path: Optional[Path] = None,
    ):
        self.http = http
        self.sm = state_machine
        self.device_id = device_id
        self.enrollment_key = enrollment_key
        self.capabilities = capabilities
        self.hostname = hostname
        self.platform = platform
        self.agent_version = agent_version
        self.token_path = Path(token_path) if token_path else Path("agent_token.json")

        self.node_id: Optional[str] = None
        self.token: Optional[str] = None

    # ── Persisted token helpers ─────────────────────────────────────

    def _load_stored_identity(self) -> bool:
        """Load previously stored node_id + token. Returns True if found."""
        if not self.token_path.exists():
            return False
        try:
            with open(self.token_path) as f:
                data = json.load(f)
            if data.get("device_id") == self.device_id and data.get("node_id") and data.get("token"):
                self.node_id = data["node_id"]
                self.token = data["token"]
                self.http.update_token(self.token)
                logger.info("Loaded stored identity: node_id=%s", self.node_id)
                # Walk through valid transitions to reach ACTIVE
                self.sm.transition_to(NodeState.ENROLLING)
                self.sm.transition_to(NodeState.ACTIVE)
                return True
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load stored identity: %s", exc)
        return False

    def _save_identity(self):
        """Persist node_id and token to disk."""
        try:
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_path, "w") as f:
                json.dump({
                    "device_id": self.device_id,
                    "node_id": self.node_id,
                    "token": self.token,
                }, f)
            logger.info("Saved identity to %s", self.token_path)
        except OSError as exc:
            logger.warning("Failed to save identity: %s", exc)

    # ── Registration steps ──────────────────────────────────────────

    def _send_register(self) -> dict:
        """POST /nodes/register/. Returns response data."""
        resp = self.http.register(
            device_id=self.device_id,
            enrollment_key=self.enrollment_key,
            capabilities=self.capabilities,
            hostname=self.hostname,
            platform=self.platform,
            agent_version=self.agent_version,
        )
        if resp.status_code == 201:
            return resp.data
        if resp.status_code == 401:
            raise RegistrationError("Invalid or inactive enrollment key")
        if resp.status_code == 400:
            errors = resp.data.get("error", resp.data) if resp.data else {}
            raise RegistrationError(f"Registration rejected: {errors}")
        raise TransportError(f"Unexpected response {resp.status_code}: {resp.data}")

    def _send_activate(self) -> bool:
        """PUT /nodes/{id}/activate/. Returns True on success."""
        resp = self.http.activate(self.node_id)
        if resp.ok:
            return True
        logger.warning("Activation returned %s: %s", resp.status_code, resp.data)
        return False

    # ── Public API ──────────────────────────────────────────────────

    def register(self, force: bool = False) -> bool:
        """Run the full registration flow.

        Args:
            force: If True, ignore any stored token and re-register.

        Returns:
            True if the node is registered and active.
        """
        # Step 1 — try stored identity
        if not force and self._load_stored_identity():
            self.sm.transition_to(NodeState.ACTIVE)
            return True

        # Step 2 — enroll
        self.sm.transition_to(NodeState.ENROLLING)
        logger.info(
            "Registering device_id='%s' with master at %s",
            self.device_id, self.http.base_url,
        )

        try:
            result = self._send_register()
        except (TransportError, RegistrationError) as exc:
            self.sm.transition_to(NodeState.OFFLINE)
            logger.error("Registration failed: %s", exc)
            raise

        self.node_id = result["node_id"]
        self.token = result.get("token", "")
        self.http.update_token(self.token)
        self._save_identity()
        logger.info("Registered successfully — node_id=%s", self.node_id)

        # Step 3 — activate
        if self._send_activate():
            self.sm.transition_to(NodeState.ACTIVE)
        else:
            self.sm.transition_to(NodeState.ACTIVE)

        return True

    def re_register(self) -> bool:
        """Force re-registration (used after token expiry / 401)."""
        logger.info("Re-registering (forced)...")
        self.sm.reset()
        return self.register(force=True)
