"""
Windows Service Manager — install/uninstall the agent as a background
Windows service using NSSM (Non-Sucking Service Manager).

Usage::

    # Install (run once)
    dtask-agent --install-service --enrollment-key KEY --master-url URL

    # Uninstall
    dtask-agent --uninstall-service

    # Status
    dtask-agent --service-status
"""

import logging
import os
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

SERVICE_NAME = "DTaskAgent"
SERVICE_DISPLAY_NAME = "DTask Agent — Distributed Task Orchestration"
NSSM_URL = "https://nssm.cc/release/nssm-2.24.zip"
NSSM_ZIP = "nssm-2.24.zip"
NSSM_DIR = "nssm-2.24"
NSSM_EXE = "nssm.exe"


# ── Path helpers ───────────────────────────────────────────────────────

def _get_agent_exe() -> str:
    """Return the path to the running agent executable."""
    return sys.executable


def _get_nssm_dir() -> Path:
    """Return the directory where NSSM is (or should be) stored."""
    return Path(__file__).parent.parent / "tools"


def _get_nssm_exe() -> Path:
    """Return the full path to the NSSM executable."""
    return _get_nssm_dir() / "nssm-2.24" / "win64" / NSSM_EXE


def _get_log_dir() -> Path:
    """Return the directory for service log files."""
    log_dir = Path(__file__).parent.parent / "service_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


# ── NSSM download ──────────────────────────────────────────────────────

def _ensure_nssm() -> Path:
    """Download NSSM if not present. Returns path to nssm.exe."""
    nssm_exe = _get_nssm_exe()
    if nssm_exe.exists():
        return nssm_exe

    logger.info("Downloading NSSM from %s ...", NSSM_URL)
    zip_path = _get_nssm_dir() / NSSM_ZIP
    _get_nssm_dir().mkdir(parents=True, exist_ok=True)

    try:
        urllib.request.urlretrieve(NSSM_URL, zip_path)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to download NSSM from {NSSM_URL}. "
            f"Download manually and place nssm.exe at {nssm_exe}"
        ) from exc

    logger.info("Extracting NSSM ...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(_get_nssm_dir())

    zip_path.unlink()  # clean up zip

    if not nssm_exe.exists():
        raise RuntimeError(f"NSSM extracted but {nssm_exe} not found")

    logger.info("NSSM ready at %s", nssm_exe)
    return nssm_exe


# ── Service commands ───────────────────────────────────────────────────

def _run_nssm(args: list[str]) -> subprocess.CompletedProcess:
    """Run an NSSM command and return the result."""
    nssm = _ensure_nssm()
    cmd = [str(nssm)] + args
    logger.debug("Running: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )


def install_service(
    master_url: str,
    enrollment_key: str,
    fallback_url: str = "",
    device_id: str = "",
    log_level: str = "INFO",
) -> bool:
    """Install the agent as a Windows service.

    Returns True on success.
    """
    agent_exe = _get_agent_exe()
    log_dir = _get_log_dir()

    # Build argument list for the service
    args = [
        f'--master-url={master_url}',
        f'--enrollment-key={enrollment_key}',
        f'--log-level={log_level}',
    ]
    if fallback_url:
        args.append(f'--fallback-url={fallback_url}')
    if device_id:
        args.append(f'--device-id={device_id}')

    logger.info("Installing service '%s' ...", SERVICE_NAME)
    logger.info("  Executable: %s", agent_exe)
    logger.info("  Arguments:  %s", " ".join(args))

    # Check if already installed
    status = _run_nssm(["status", SERVICE_NAME])
    if status.returncode == 0:
        logger.warning("Service '%s' is already installed. Removing first ...", SERVICE_NAME)
        uninstall_service()

    # Install
    result = _run_nssm(["install", SERVICE_NAME, agent_exe] + args)
    if result.returncode != 0:
        logger.error("Install failed: %s", result.stderr.strip() or result.stdout.strip())
        return False

    # Configure stdout/stderr logging
    _run_nssm(["set", SERVICE_NAME, "AppStdout", str(log_dir / "stdout.log")])
    _run_nssm(["set", SERVICE_NAME, "AppStderr", str(log_dir / "stderr.log")])

    # Set service to auto-start
    _run_nssm(["set", SERVICE_NAME, "Start", "SERVICE_AUTO_START"])

    # Set failure actions: restart on crash
    _run_nssm(["set", SERVICE_NAME, "AppThrottle", "0"])  # no throttling
    _run_nssm(["set", SERVICE_NAME, "AppExit", "Restart"])  # restart on exit

    # Set display name
    _run_nssm(["set", SERVICE_NAME, "DisplayName", SERVICE_DISPLAY_NAME])

    # Start the service
    logger.info("Starting service ...")
    result = _run_nssm(["start", SERVICE_NAME])
    if result.returncode != 0:
        logger.warning("Service installed but may not have started: %s",
                        result.stderr.strip() or result.stdout.strip())
        return False

    logger.info("Service '%s' installed and started successfully.", SERVICE_NAME)
    return True


def uninstall_service() -> bool:
    """Stop and remove the Windows service.

    Returns True on success.
    """
    logger.info("Stopping service '%s' ...", SERVICE_NAME)

    # Stop first (ignore errors if already stopped)
    _run_nssm(["stop", SERVICE_NAME])

    logger.info("Removing service '%s' ...", SERVICE_NAME)
    result = _run_nssm(["remove", SERVICE_NAME, "confirm"])
    if result.returncode != 0:
        logger.error("Uninstall failed: %s", result.stderr.strip() or result.stdout.strip())
        return False

    logger.info("Service '%s' removed successfully.", SERVICE_NAME)
    return True


def service_status() -> str:
    """Return the current status of the service."""
    result = _run_nssm(["status", SERVICE_NAME])
    if result.returncode != 0:
        # NSSM returns non-zero when service doesn't exist
        return "not_installed"
    return result.stdout.strip()


# ── CLI handler ────────────────────────────────────────────────────────

def handle_service_command(args) -> int:
    """Dispatch service subcommands. Returns exit code."""
    if args.install_service:
        if not args.master_url:
            print("ERROR: --master-url is required for --install-service")
            return 1
        if not args.enrollment_key:
            print("ERROR: --enrollment-key is required for --install-service")
            return 1

        success = install_service(
            master_url=args.master_url,
            enrollment_key=args.enrollment_key,
            fallback_url=args.fallback_url or "",
            device_id=args.device_id or "",
            log_level=args.log_level or "INFO",
        )
        return 0 if success else 1

    if args.uninstall_service:
        success = uninstall_service()
        return 0 if success else 1

    if args.service_status:
        status = service_status()
        print(f"DTask Agent service status: {status}")
        if status == "running":
            # Show PID and uptime
            result = _run_nssm(["status", SERVICE_NAME])
            print(f"  NSSM status: {result.stdout.strip()}")
        return 0

    return 2  # no service command matched
