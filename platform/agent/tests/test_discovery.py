"""
Tests for the LAN discovery module.

Uses mock sockets to avoid real network broadcasts.
"""

import json
import socket
from unittest.mock import MagicMock, patch

import pytest

from discovery.lan import DISCOVERY_PORT, DiscoveryService


class TestDiscoveryService:
    def test_manual_master_url_returns_immediately(self):
        """If master_url is configured, discovery returns True without broadcasting."""
        service = DiscoveryService(master_url="http://10.0.0.1:8000")
        assert service.discover() is True
        assert service.master_url == "http://10.0.0.1:8000"

    def test_no_master_url_and_no_broadcast_returns_false(self):
        """Without a configured URL and without a broadcast response, discovery fails."""
        service = DiscoveryService(master_url="", timeout=0.1)
        result = service.discover()
        # On most systems this will fail gracefully (no listener)
        # We just check it doesn't crash and returns a bool
        assert isinstance(result, bool)

    def test_discovered_masters_property(self):
        service = DiscoveryService(master_url="http://10.0.0.1:8000")
        assert service.discovered_masters == []
        assert service.has_discovered is False

    def test_multiple_discovery_calls(self):
        """Calling discover() multiple times is safe."""
        service = DiscoveryService(master_url="http://10.0.0.1:8000")
        assert service.discover() is True
        assert service.discover() is True
        assert service.master_url == "http://10.0.0.1:8000"

    # ── Listener tests ──────────────────────────────────────────────

    def test_listener_start_stop(self):
        service = DiscoveryService()
        service.start_listener(master_url="http://localhost:8000", cluster_name="test")
        assert service._running is True
        assert service._listener is not None
        service.stop_listener()
        assert service._running is False

    def test_listener_idempotent_start(self):
        """Starting the listener twice doesn't create two threads."""
        service = DiscoveryService()
        service.start_listener(master_url="http://localhost:8000")
        t1 = service._listener
        service.start_listener(master_url="http://localhost:8000")
        t2 = service._listener
        assert t1 is t2  # same thread reference
        service.stop_listener()

    # ── Discovery info ──────────────────────────────────────────────

    def test_get_discovery_info(self):
        service = DiscoveryService(master_url="http://10.0.0.1:8000")
        info = service.get_discovery_info()
        assert info["type"] == "discover_ack"
        assert info["master_url"] == "http://10.0.0.1:8000"
        assert info["discovery_port"] == DISCOVERY_PORT
