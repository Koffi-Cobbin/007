#!/usr/bin/env python
"""
dtask-agent — Distributed Task Orchestration Platform agent.

Entry point for the device agent. Connects to the Django control plane,
registers the device, and begins sending heartbeats and polling for tasks.

Usage:
    python main.py --config config/agent.yaml
    python main.py --device-id my-laptop --enrollment-key abc123
"""

import argparse
import logging
import os
import signal
import sys
import time
import threading

from agent_core.registration import RegistrationError, RegistrationFlow
from agent_core.scheduler import AgentScheduler
from agent_core.state_machine import NodeState, StateMachine
from config.settings import load_config
from discovery.lan import DiscoveryService
from executor.runner import TaskRunner
from transport.http_client import HttpClient, UnauthorizedError


def setup_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="dtask-agent — Distributed Task Orchestration Platform agent")
    parser.add_argument("--config", help="Path to YAML config file")
    parser.add_argument("--master-url", help="Backend URL (e.g. http://10.0.0.1:8000)")
    parser.add_argument("--fallback-url", help="Fallback backend URL for master failover")
    parser.add_argument("--device-id", help="Unique device identifier (defaults to hostname)")
    parser.add_argument("--enrollment-key", help="Pre-shared enrollment key")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging level")
    parser.add_argument("--discovery-port", type=int, help="UDP port for LAN discovery")
    parser.add_argument("--discovery-timeout", type=float, help="Seconds to wait for discovery responses")
    # Windows service management (Phase 8)
    parser.add_argument("--install-service", action="store_true",
                        help="Install as a Windows background service (requires --master-url and --enrollment-key)")
    parser.add_argument("--uninstall-service", action="store_true",
                        help="Remove the Windows service")
    parser.add_argument("--service-status", action="store_true",
                        help="Check if the Windows service is installed/running")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> dict:
    """Merge config file with CLI overrides. CLI takes precedence."""
    config = load_config(args.config)

    if args.master_url:
        config["master_url"] = args.master_url
    if args.fallback_url:
        config["fallback_url"] = args.fallback_url
    if args.device_id:
        config["device_id"] = args.device_id
    if args.enrollment_key:
        config["enrollment_key"] = args.enrollment_key
    if args.log_level:
        config["log_level"] = args.log_level
    if args.discovery_port:
        config["discovery_port"] = args.discovery_port
    if args.discovery_timeout:
        config["discovery_timeout"] = args.discovery_timeout

    return config


def detect_platform() -> str:
    import platform
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


def detect_hostname() -> str:
    import platform
    return platform.node() or ""


def build_capabilities(config: dict) -> dict:
    """Auto-detect capabilities not explicitly set in config."""
    caps = dict(config.get("capabilities", {}))

    if not caps.get("cpu_cores"):
        try:
            import psutil
            caps["cpu_cores"] = psutil.cpu_count(logical=True) or 0
        except ImportError:
            caps["cpu_cores"] = 0

    if not caps.get("memory_mb"):
        try:
            import psutil
            caps["memory_mb"] = psutil.virtual_memory().total // (1024 * 1024)
        except ImportError:
            caps["memory_mb"] = 0

    if not caps.get("os_family"):
        caps["os_family"] = detect_platform()

    if not caps.get("os_distribution"):
        caps["os_distribution"] = detect_platform()

    return caps


def _handle_task_received(task_data: dict, runner: TaskRunner, scheduler: AgentScheduler, http: HttpClient, node_id: str):
    """Callback when a task is received from the backend."""
    try:
        result = runner.execute(task_data)
        http.submit_result(
            task_id=task_data["task_id"],
            status=result["status"],
            output=result.get("output"),
            error=result.get("error"),
            metrics=result.get("metrics"),
            logs=result.get("logs", ""),
        )
    except Exception as exc:
        logging.getLogger(__name__).error("Task execution failed: %s", exc)
        try:
            http.submit_result(
                task_id=task_data["task_id"],
                status="failed",
                error={"code": "EXECUTION_ERROR", "message": str(exc)},
            )
        except Exception:
            pass
    finally:
        scheduler.on_task_completed()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = build_config(args)
    setup_logging(config["log_level"])
    logger = logging.getLogger(__name__)

    # ── Windows service management ──────────────────────────────────
    if args.install_service or args.uninstall_service or args.service_status:
        from agent_core.service import handle_service_command
        return handle_service_command(args)

    logger.info("dtask-agent v%s starting", config.get("agent_version", "unknown"))
    logger.info("Config loaded from: %s", config.get("_config_path", "unknown"))

    primary_url = config["master_url"]
    fallback_url = config.get("fallback_url", "")
    current_url = primary_url
    if fallback_url:
        logger.info("Primary master: %s | Fallback master: %s", primary_url, fallback_url)
    else:
        logger.info("Master URL: %s (no fallback configured)", primary_url)

    # ── Components ──────────────────────────────────────────────────
    sm = StateMachine()
    http = HttpClient(base_url=current_url)
    discovery = DiscoveryService(
        master_url=config["master_url"],
        discovery_port=config.get("discovery_port", 42069),
        timeout=config.get("discovery_timeout", 3.0),
        hostname=detect_hostname(),
    )
    runner = TaskRunner()

    # ── Discover master ─────────────────────────────────────────────
    if not discovery.discover():
        logger.error("No master found. Set master_url in config or use --master-url")
        return 1

    # Update http base_url in case discovery found a different master
    discovered_url = discovery.master_url
    if discovered_url != config["master_url"]:
        logger.info("Using discovered master: %s", discovered_url)
        http = HttpClient(base_url=discovered_url)

    # ── Register ────────────────────────────────────────────────────
    capabilities = build_capabilities(config)
    registration = RegistrationFlow(
        http=http,
        state_machine=sm,
        device_id=config["device_id"],
        enrollment_key=config["enrollment_key"],
        capabilities=capabilities,
        hostname=detect_hostname(),
        platform=detect_platform(),
        agent_version=config["agent_version"],
        token_path=(
            os.path.join(config.get("data_dir", "."), "agent_token.json")
        ),
    )

    try:
        registration.register()
    except (RegistrationError, UnauthorizedError) as exc:
        if fallback_url and current_url != fallback_url:
            logger.warning("Registration failed on primary, trying fallback: %s", fallback_url)
            current_url = fallback_url
            http = HttpClient(base_url=current_url)
            registration = RegistrationFlow(
                http=http, state_machine=sm,
                device_id=config["device_id"],
                enrollment_key=config["enrollment_key"],
                capabilities=capabilities,
                hostname=detect_hostname(), platform=detect_platform(),
                agent_version=config["agent_version"],
                token_path=os.path.join(config.get("data_dir", "."), "agent_token.json"),
            )
            try:
                registration.register()
            except (RegistrationError, UnauthorizedError) as exc2:
                logger.error("Registration failed on both primary and fallback: %s", exc2)
                return 1
        else:
            logger.error("Registration failed: %s", exc)
            return 1

    logger.info("Agent registered — node_id=%s, state=%s", registration.node_id, sm.current_value)

    # ── Start scheduler ─────────────────────────────────────────────
    scheduler = AgentScheduler(
        http=http,
        state_machine=sm,
        node_id=registration.node_id,
        heartbeat_interval=config.get("heartbeat_interval", 30),
        task_poll_interval=config.get("task_poll_interval", 5),
        on_task_received=lambda td: _handle_task_received(td, runner, scheduler, http, registration.node_id),
    )
    scheduler.start()

    # ── Wait for shutdown ─────────────────────────────────────────────
    shutdown_event = threading.Event()

    def _handle_signal(signum, frame):
        logger.info("Received signal %s, shutting down...", signum)
        scheduler.stop()
        http.close()
        shutdown_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("Agent running. Press Ctrl+C to stop.")
    shutdown_event.wait()
    logger.info("Agent stopped.")
    return 0


if __name__ == "__main__":
    import threading
    sys.exit(main())
