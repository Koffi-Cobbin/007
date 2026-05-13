"""
Task executor — runs assigned tasks using the plugin handler registry.

Phase 7: dispatches to plugin-based handlers discovered automatically
from ``executor/handlers/`` and ``plugins/`` directories.
"""

import logging
import time

from executor.loader import get_handler

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300


class TaskRunner:
    """Executes tasks assigned by the backend.

    Dispatches to the appropriate ``BaseWorkloadHandler`` subclass
    based on ``task_type``.  Handlers are discovered automatically
    by the plugin loader — no manual registration needed.
    """

    def execute(self, task_data: dict) -> dict:
        """Execute a task and return a result dict.

        Args:
            task_data: Task payload from the backend
                (task_id, task_type, payload, deadline_seconds, etc.)

        Returns:
            dict with keys: status, output, error, metrics, logs
        """
        task_type = task_data.get("task_type", "unknown")
        payload = task_data.get("payload", {})
        timeout = task_data.get("deadline_seconds", DEFAULT_TIMEOUT)

        logger.info("Executing task type=%s timeout=%ss", task_type, timeout)

        handler = get_handler(task_type)
        if handler is None:
            return {
                "status": "failed",
                "output": {},
                "error": {
                    "code": "UNKNOWN_TASK_TYPE",
                    "message": (
                        f"No handler registered for task_type='{task_type}'. "
                        f"Install a plugin in the plugins/ directory."
                    ),
                },
                "metrics": {},
                "logs": f"Unknown task type: {task_type}\n",
            }

        start = time.time()
        try:
            result = handler.execute(payload, timeout)
            elapsed = time.time() - start
            result.setdefault("metrics", {})
            result["metrics"]["duration_seconds"] = round(elapsed, 2)
            return result
        except Exception as exc:
            elapsed = time.time() - start
            logger.error("Handler crashed for task_type=%s: %s", task_type, exc)
            return {
                "status": "failed",
                "output": {},
                "error": {"code": "HANDLER_CRASH", "message": str(exc)},
                "metrics": {"duration_seconds": round(elapsed, 2)},
                "logs": f"Handler exception: {exc}\n",
            }
