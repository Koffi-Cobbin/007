"""
HTTP client wrapping the requests library for agent-to-backend communication.

Handles authentication headers, base URL resolution, and common error patterns.
"""

from dataclasses import dataclass, field
from typing import Optional

import requests


class TransportError(Exception):
    """Raised when a request fails after all retries."""


class UnauthorizedError(TransportError):
    """Raised when the backend returns 401 — token may be invalid."""


@dataclass
class HttpResponse:
    status_code: int
    data: dict | list | None
    headers: dict = field(default_factory=dict)

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    @property
    def no_content(self):
        return self.status_code == 204


class HttpClient:
    """Lightweight REST client for the orchestration backend."""

    def __init__(
        self,
        base_url: str,
        token: str = "",
        timeout: int = 30,
        max_retries: int = 2,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json; version=1.0",
            "Content-Type": "application/json",
        })

    def update_token(self, token: str):
        """Update the bearer token (e.g. after registration)."""
        self.token = token

    def _headers(self) -> dict:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, path: str, **kwargs) -> HttpResponse:
        url = f"{self.base_url}{path}"
        attempt = 0
        last_error = None

        while attempt <= self.max_retries:
            try:
                response = self._session.request(
                    method,
                    url,
                    headers={**self._session.headers, **self._headers(), **kwargs.pop("headers", {})},
                    timeout=self.timeout,
                    **kwargs,
                )
            except requests.RequestException as exc:
                attempt += 1
                if attempt > self.max_retries:
                    raise TransportError(f"Request failed after {self.max_retries} retries: {exc}") from exc
                continue

            if response.status_code == 401:
                raise UnauthorizedError(f"401 Unauthorized at {path} — token may be invalid")

            try:
                data = response.json() if response.content else None
            except ValueError:
                data = None

            return HttpResponse(
                status_code=response.status_code,
                data=data,
                headers=dict(response.headers),
            )

        raise TransportError(f"Request failed: {last_error}")

    def get(self, path: str, params: dict | None = None) -> HttpResponse:
        return self._request("GET", path, params=params)

    def post(self, path: str, json_data: dict | None = None) -> HttpResponse:
        return self._request("POST", path, json=json_data or {})

    def put(self, path: str, json_data: dict | None = None) -> HttpResponse:
        return self._request("PUT", path, json=json_data or {})

    # ── Convenience helpers ──────────────────────────────────────────

    def register(self, device_id: str, enrollment_key: str, capabilities: dict,
                 hostname: str = "", platform: str = "", agent_version: str = "") -> HttpResponse:
        return self.post("/api/v1/nodes/register/", {
            "device_id": device_id,
            "hostname": hostname,
            "platform": platform,
            "enrollment_key": enrollment_key,
            "agent_version": agent_version,
            "capabilities": capabilities,
        })

    def activate(self, node_id: str) -> HttpResponse:
        return self.put(f"/api/v1/nodes/{node_id}/activate/", {"status": "active"})

    def send_heartbeat(self, node_id: str, status: str, load: float,
                       current_task: str | None = None,
                       resources: dict | None = None,
                       uptime: int = 0) -> HttpResponse:
        return self.post(f"/api/v1/nodes/{node_id}/heartbeat/", {
            "status": status,
            "current_load": load,
            "current_task": current_task,
            "resources": resources or {},
            "uptime_seconds": uptime,
        })

    def poll_task(self, node_id: str, capabilities: list[str] | None = None) -> HttpResponse:
        params = {"node_id": node_id}
        if capabilities:
            params["capabilities"] = ",".join(capabilities)
        return self.get("/api/v1/tasks/assign/", params=params)

    def submit_result(self, task_id: str, status: str, output: dict | None = None,
                      error: dict | None = None, metrics: dict | None = None,
                      logs: str = "") -> HttpResponse:
        return self.post(f"/api/v1/tasks/{task_id}/result/", {
            "status": status,
            "output": output or {},
            "error": error,
            "metrics": metrics or {},
            "logs": logs,
        })

    def report_capabilities(self, node_id: str, capabilities: dict) -> HttpResponse:
        return self.post(f"/api/v1/nodes/{node_id}/capabilities/", capabilities)

    def close(self):
        self._session.close()
