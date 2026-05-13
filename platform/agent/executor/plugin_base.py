"""
Abstract base class for all workload handlers (built-in and third-party).

Any class that inherits from ``BaseWorkloadHandler`` and is placed in the
``executor/handlers/`` or ``plugins/`` directory is automatically
discovered by the plugin loader.

Example::

    from executor.plugin_base import BaseWorkloadHandler

    class GreetHandler(BaseWorkloadHandler):
        name = "greet"
        description = "Returns a friendly greeting"
        version = "1.0.0"

        def validate(self, payload):
            errors = []
            if "name" not in payload:
                errors.append("Missing required field: 'name'")
            return errors

        def execute(self, payload, timeout):
            name = payload.get("name", "world")
            return {
                "status": "completed",
                "output": {"greeting": f"Hello, {name}!", "name": name},
                "error": None,
                "logs": "",
            }
"""

from abc import ABC, abstractmethod


class BaseWorkloadHandler(ABC):
    """Abstract handler that every workload plugin must subclass.

    Class attributes (set by each subclass):

    ==============  ===============================================
    Attribute       Purpose
    ==============  ===============================================
    ``name``        Unique task type identifier (e.g. ``"checksum"``)
    ``description`` Human-readable summary
    ``version``     Semver string (e.g. ``"1.0.0"``)
    ==============  ===============================================
    """

    name: str = ""
    description: str = ""
    version: str = "1.0.0"

    @abstractmethod
    def validate(self, payload: dict) -> list:
        """Validate *payload* and return a list of error messages.

        Return an empty list if the payload is valid.
        """

    @abstractmethod
    def execute(self, payload: dict, timeout: int) -> dict:
        """Execute the task.

        Returns a dict with keys:
            status  — ``"completed"`` or ``"failed"``
            output  — dict of result data
            error   — ``None`` or ``{"code": ..., "message": ...}``
            logs    — optional text string
            metrics — optional dict with ``duration_seconds`` etc.
        """
