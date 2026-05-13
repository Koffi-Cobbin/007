"""
Periodic task scheduler — runs heartbeats and task polling on timers.

Uses threading.Timer for non-blocking periodic execution.
Allows graceful shutdown via the stop() method.
"""

import logging
import threading
import time
from typing import Callable, Optional

from agent_core.state_machine import NodeState, StateMachine
from transport.http_client import HttpClient, TransportError, UnauthorizedError

logger = logging.getLogger(__name__)


class AgentScheduler:
    """Manages periodic agent tasks: heartbeats and task polling."""

    def __init__(
        self,
        http: HttpClient,
        state_machine: StateMachine,
        node_id: str,
        heartbeat_interval: int = 30,
        task_poll_interval: int = 5,
        on_task_received: Optional[Callable] = None,
    ):
        self.http = http
        self.sm = state_machine
        self.node_id = node_id
        self.heartbeat_interval = heartbeat_interval
        self.task_poll_interval = task_poll_interval
        self.on_task_received = on_task_received

        self._heartbeat_timer: Optional[threading.Timer] = None
        self._poll_timer: Optional[threading.Timer] = None
        self._running = False
        self._start_time: float = 0.0

    # ── Heartbeat ───────────────────────────────────────────────────

    def _send_heartbeat(self):
        """Send a single heartbeat and reschedule."""
        if not self._running:
            return

        try:
            current_load = _get_cpu_load()
            resp = self.http.send_heartbeat(
                node_id=self.node_id,
                status=self.sm.current_value,
                load=current_load,
                resources=_get_resource_summary(),
                uptime=int(time.time() - self._start_time),
            )
            if resp.ok:
                logger.debug("Heartbeat sent (status=%s, load=%.2f)", self.sm.current_value, current_load)
            else:
                logger.warning("Heartbeat returned %s: %s", resp.status_code, resp.data)
        except UnauthorizedError:
            logger.error("Heartbeat failed: unauthorized — will re-register")
            self.sm.transition_to(NodeState.OFFLINE)
            return
        except TransportError as exc:
            logger.warning("Heartbeat failed: %s", exc)
            # Don't change state — transient network issue

        self._schedule_heartbeat()

    def _schedule_heartbeat(self):
        if self._running:
            self._heartbeat_timer = threading.Timer(self.heartbeat_interval, self._send_heartbeat)
            self._heartbeat_timer.daemon = True
            self._heartbeat_timer.start()

    # ── Task polling ────────────────────────────────────────────────

    def _poll_for_task(self):
        """Poll the backend for an available task."""
        if not self._running:
            return

        try:
            resp = self.http.poll_task(node_id=self.node_id)
            if resp.no_content:
                logger.debug("No tasks available")
            elif resp.ok and resp.data:
                task_data = resp.data
                logger.info("Task received: %s (type=%s)", task_data["task_id"], task_data.get("task_type"))
                self.sm.transition_to(NodeState.BUSY)
                if self.on_task_received:
                    self.on_task_received(task_data)
            else:
                logger.debug("Poll returned %s", resp.status_code)
        except UnauthorizedError:
            logger.error("Task poll failed: unauthorized")
            self.sm.transition_to(NodeState.OFFLINE)
            return
        except TransportError as exc:
            logger.debug("Task poll failed (will retry): %s", exc)

        self._schedule_poll()

    def _schedule_poll(self):
        if self._running:
            self._poll_timer = threading.Timer(self.task_poll_interval, self._poll_for_task)
            self._poll_timer.daemon = True
            self._poll_timer.start()

    # ── Lifecycle ───────────────────────────────────────────────────

    def start(self):
        """Begin periodic heartbeat and task polling."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        self._start_time = time.time()
        logger.info(
            "Starting scheduler (heartbeat=%ss, poll=%ss)",
            self.heartbeat_interval, self.task_poll_interval,
        )
        self._schedule_heartbeat()
        self._schedule_poll()

    def stop(self):
        """Stop all periodic tasks. Safe to call multiple times."""
        self._running = False
        if self._heartbeat_timer:
            self._heartbeat_timer.cancel()
        if self._poll_timer:
            self._poll_timer.cancel()
        logger.info("Scheduler stopped")

    def on_task_completed(self):
        """Call when the current task finishes executing."""
        if self.sm.current == NodeState.BUSY:
            self.sm.transition_to(NodeState.IDLE)

    def on_degraded(self):
        """Call when the node enters a degraded state."""
        if self.sm.can_transition_to(NodeState.DEGRADED):
            self.sm.transition_to(NodeState.DEGRADED)


# ── Resource helpers ───────────────────────────────────────────────

def _get_cpu_load() -> float:
    """Return current CPU load as a 0.0–1.0 value."""
    try:
        import psutil
        return psutil.cpu_percent(interval=0) / 100.0
    except ImportError:
        return 0.0


def _get_resource_summary() -> dict:
    """Return a dict of current resource usage."""
    result = {}
    try:
        import psutil
        result["cpu_percent"] = psutil.cpu_percent(interval=0)
        result["memory_used_mb"] = psutil.virtual_memory().used // (1024 * 1024)
        result["memory_percent"] = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/")
        result["disk_free_mb"] = disk.free // (1024 * 1024)
    except ImportError:
        pass
    return result
