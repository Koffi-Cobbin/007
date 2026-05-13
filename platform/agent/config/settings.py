"""
Agent configuration loader.

Loads settings from a YAML config file with environment variable overrides.
"""

import os
from pathlib import Path

import yaml


DEFAULT_CONFIG_PATHS = [
    Path("agent.yaml"),
    Path("config/agent.yaml"),
    Path.home() / ".config" / "dtask-agent" / "agent.yaml",
    Path("/etc/dtask-agent/agent.yaml"),
]


def _merge_env_overrides(config, prefix="DTASK_"):
    """Override config values from environment variables prefixed with prefix.

    Example:  DTASK_MASTER_URL=http://10.0.0.1:8000
              DTASK_DEVICE_ID=my-laptop-01
    """
    for key, value in os.environ.items():
        if key.startswith(prefix):
            config_key = key[len(prefix):].lower()
            config[config_key] = value
    return config


def load_config(config_path=None):
    """Load agent configuration from YAML file with env overrides.

    Resolution order:
      1. Explicit config_path argument
      2. DTASK_CONFIG_PATH environment variable
      3. Default search paths (agent.yaml → config/agent.yaml → ~/.config/... → /etc/...)
      4. All of the above, then environment variable overrides
    """
    resolved_path = None

    if config_path:
        resolved_path = Path(config_path)
    elif "DTASK_CONFIG_PATH" in os.environ:
        resolved_path = Path(os.environ["DTASK_CONFIG_PATH"])

    if resolved_path and resolved_path.exists():
        with open(resolved_path) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}
        for candidate in DEFAULT_CONFIG_PATHS:
            if candidate.exists():
                with open(candidate) as f:
                    config = yaml.safe_load(f) or {}
                resolved_path = candidate
                break

    # Strip empty-string YAML values for fields that have computed defaults,
    # so the setdefault() calls below take effect.
    for key in ("device_id", "master_url", "data_dir", "log_level"):
        if key in config and config[key] == "":
            del config[key]

    # Apply env overrides
    config = _merge_env_overrides(config)

    # Fill defaults
    config.setdefault("master_url", "http://localhost:8000")
    config.setdefault("fallback_url", "")
    config.setdefault("device_id", _default_device_id())
    config.setdefault("enrollment_key", "")
    config.setdefault("agent_version", "1.0.0")
    config.setdefault("heartbeat_interval", 30)
    config.setdefault("task_poll_interval", 5)
    config.setdefault("log_level", "INFO")
    config.setdefault("data_dir", str(Path.cwd() / "agent_data"))
    config.setdefault("discovery_port", 42069)
    config.setdefault("discovery_timeout", 3.0)
    config.setdefault("capabilities", {})

    config["_config_path"] = str(resolved_path) if resolved_path else "defaults"
    return config


def _default_device_id():
    """Generate a stable default device identifier."""
    import platform
    hostname = platform.node()
    if hostname:
        return hostname
    import uuid
    return f"device-{uuid.uuid4().hex[:8]}"
