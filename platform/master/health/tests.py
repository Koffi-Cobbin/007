"""
Tests for health/readiness endpoints (Phase 8 — Multi-Master Readiness).
"""

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient


class HealthEndpointTests(TestCase):
    """GET /health/ returns liveness info."""

    def setUp(self):
        self.client = APIClient()

    def test_health_returns_200(self):
        resp = self.client.get("/health/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "alive")
        self.assertIn("uptime_seconds", resp.data)
        self.assertIn("version", resp.data)

    def test_health_no_auth_required(self):
        """Health endpoint is public — no authentication needed."""
        resp = self.client.get("/health/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_health_includes_version(self):
        resp = self.client.get("/health/")
        self.assertEqual(resp.data["version"], "1.0.0")


class ReadinessEndpointTests(TestCase):
    """GET /ready/ returns readiness including database status."""

    def setUp(self):
        self.client = APIClient()

    def test_readiness_returns_200_when_db_ok(self):
        resp = self.client.get("/ready/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "ready")
        self.assertTrue(resp.data["database"]["ok"])

    def test_readiness_no_auth_required(self):
        resp = self.client.get("/ready/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
