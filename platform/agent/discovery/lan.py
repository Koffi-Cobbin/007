"""
LAN discovery module — finds masters and peers on the local network via UDP broadcast.

Two modes:
  1. **Broadcast discovery** — sends a UDP beacon to 255.255.255.255:PORT asking
     "who is the master?" and listens for responses.
  2. **Manual join** — uses a pre-configured master URL.

The beacon protocol is JSON over UDP:
  Request:  {"type": "discover", "agent_id": "<hostname>"}
  Response: {"type": "discover_ack", "cluster_name": "...", "master_url": "..."}
"""

import json
import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

DISCOVERY_PORT = 42069
DISCOVERY_TIMEOUT = 3.0  # seconds to wait for responses
BROADCAST_ADDR = "255.255.255.255"


@dataclass
class DiscoveredMaster:
    """Represents a master discovered on the LAN."""
    cluster_name: str
    master_url: str
    master_hostname: str = ""
    api_version: str = "1.0"
    discovered_at: float = field(default_factory=time.time)

    @property
    def age_seconds(self) -> float:
        return time.time() - self.discovered_at


class DiscoveryService:
    """Discovers masters and peers on the local network."""

    def __init__(
        self,
        master_url: str = "",
        discovery_port: int = DISCOVERY_PORT,
        timeout: float = DISCOVERY_TIMEOUT,
        hostname: str = "",
    ):
        self._configured_master_url = master_url
        self._discovery_port = discovery_port
        self._timeout = timeout
        self._hostname = hostname or socket.gethostname()

        self._discovered_masters: list[DiscoveredMaster] = []
        self._listener: Optional[threading.Thread] = None
        self._running = False

    @property
    def master_url(self) -> str:
        """Return the discovered or configured master URL."""
        if self._discovered_masters:
            return self._discovered_masters[0].master_url
        return self._configured_master_url

    @property
    def discovered_masters(self) -> list[DiscoveredMaster]:
        return list(self._discovered_masters)

    @property
    def has_discovered(self) -> bool:
        return len(self._discovered_masters) > 0

    # ── Broadcast send ──────────────────────────────────────────────

    def _send_broadcast(self) -> bool:
        """Send a UDP discovery beacon. Returns True if sent successfully."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(self._timeout)

            payload = json.dumps({
                "type": "discover",
                "agent_id": self._hostname,
            })
            sock.sendto(payload.encode(), (BROADCAST_ADDR, self._discovery_port))
            logger.debug("Sent discovery beacon on port %s", self._discovery_port)

            # Listen for responses
            self._discovered_masters = []
            start = time.time()
            while time.time() - start < self._timeout:
                try:
                    data, addr = sock.recvfrom(4096)
                    response = json.loads(data.decode())
                    if response.get("type") == "discover_ack":
                        master = DiscoveredMaster(
                            cluster_name=response.get("cluster_name", "unknown"),
                            master_url=response.get("master_url", f"http://{addr[0]}:8000"),
                            master_hostname=response.get("master_hostname", addr[0]),
                            api_version=response.get("api_version", "1.0"),
                        )
                        self._discovered_masters.append(master)
                        logger.info("Discovered master: %s at %s", master.cluster_name, master.master_url)
                except socket.timeout:
                    break
                except json.JSONDecodeError:
                    continue

            sock.close()
            return len(self._discovered_masters) > 0

        except OSError as exc:
            logger.warning("Broadcast discovery failed: %s", exc)
            return False

    # ── Beacon listener (for master nodes) ──────────────────────────

    def start_listener(self, master_url: str, cluster_name: str = "default"):
        """Start a UDP listener that responds to discovery beacons.

        Call this on the master node so agents can discover it.
        """
        if self._listener and self._listener.is_alive():
            logger.warning("Listener already running")
            return

        self._running = True
        self._listener = threading.Thread(
            target=self._listen_loop,
            args=(master_url, cluster_name),
            daemon=True,
        )
        self._listener.start()
        logger.info("Discovery listener started on port %s", self._discovery_port)

    def _listen_loop(self, master_url: str, cluster_name: str):
        """Background thread that responds to discovery beacons."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", self._discovery_port))
            sock.settimeout(1.0)

            while self._running:
                try:
                    data, addr = sock.recvfrom(4096)
                    msg = json.loads(data.decode())
                    if msg.get("type") == "discover":
                        response = json.dumps({
                            "type": "discover_ack",
                            "cluster_name": cluster_name,
                            "master_url": master_url,
                            "master_hostname": socket.gethostname(),
                            "api_version": "1.0",
                        })
                        sock.sendto(response.encode(), addr)
                        logger.debug("Responded to discover from %s", addr[0])
                except socket.timeout:
                    continue
                except json.JSONDecodeError:
                    continue

            sock.close()
        except OSError as exc:
            logger.error("Discovery listener error: %s", exc)

    def stop_listener(self):
        self._running = False

    # ── Public API ──────────────────────────────────────────────────

    def discover(self) -> bool:
        """Run discovery. Returns True if a master was found.

        Order of resolution:
          1. Manually configured master_url (from config / CLI)
          2. UDP broadcast on the LAN
          3. Fall back to HTTP discovery endpoint if master URL known
        """
        # 1. Manual config takes priority
        if self._configured_master_url:
            logger.info("Using configured master: %s", self._configured_master_url)
            return True

        # 2. UDP broadcast
        logger.info("No master configured — discovering via UDP broadcast on port %s...", self._discovery_port)
        if self._send_broadcast():
            discovered = self._discovered_masters[0]
            logger.info("Discovered master: %s at %s", discovered.cluster_name, discovered.master_url)
            return True

        logger.warning(
            "No master found via broadcast. Provide --master-url or set DTASK_MASTER_URL."
        )
        return False

    def get_discovery_info(self) -> dict:
        """Return discovery info payload for the beacon endpoint."""
        return {
            "type": "discover_ack",
            "agent_id": self._hostname,
            "master_url": self.master_url,
            "discovery_port": self._discovery_port,
        }
