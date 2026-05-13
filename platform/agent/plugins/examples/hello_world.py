"""
Example plugin — demonstrates how to add a new workload type.

To use this plugin:

1. Place this file (or any ``.py`` file with a ``BaseWorkloadHandler``
   subclass) in the ``plugins/`` directory.
2. Register the task type in the backend WorkloadType registry.
3. Submit jobs with ``task_type="hello_world"``.

The plugin loader auto-discovers this handler on agent startup.
No changes to core code are needed.
"""

from executor.plugin_base import BaseWorkloadHandler


class HelloWorldHandler(BaseWorkloadHandler):
    """Returns a friendly greeting — the simplest possible plugin."""

    name = "hello_world"
    description = "Returns a friendly greeting (example plugin)"
    version = "1.0.0"

    def validate(self, payload):
        errors = []
        if "name" not in payload:
            errors.append("Missing required field: 'name'")
        return errors

    def execute(self, payload, timeout):
        name = payload.get("name", "world")
        greeting = f"Hello, {name}! Welcome to the distributed task platform."
        return {
            "status": "completed",
            "output": {
                "greeting": greeting,
                "name": name,
                "plugin": "hello_world",
                "version": self.version,
            },
            "error": None,
            "logs": f"Greeted {name}\n",
        }
