"""
Tests for the security app — enrollment keys, audit logs, protocol versions,
and Phase 6 auth enforcement, token validation, stale node detection.
"""

from io import StringIO
from datetime import timedelta

from django.test import TestCase
from django.contrib.auth.models import User
from django.core.management import call_command
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from nodes.models import Node, NodeCapability, NodeHeartbeat
from orchestration.models import Job, Task
from .models import AuditLog, EnrollmentKey, ProtocolVersion


# ── Helpers ──────────────────────────────────────────────────────────────

def _admin_client() -> APIClient:
    User.objects.create_superuser("admin", "admin@test.com", "password")
    c = APIClient()
    c.login(username="admin", password="password")
    return c


def _authed_client(token="sec-token") -> APIClient:
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return c


# ══════════════════════════════════════════════════════════════════════════
# Enrollment Key Tests (admin auth required)
# ══════════════════════════════════════════════════════════════════════════

class EnrollmentKeyTests(TestCase):
    def setUp(self):
        self.client = _admin_client()

    def test_create_enrollment_key(self):
        resp = self.client.post("/api/v1/enrollment-keys/",
                                 {"key": "dev-key-001", "description": "Dev key"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(EnrollmentKey.objects.filter(key="dev-key-001").exists())

    def test_list_enrollment_keys(self):
        EnrollmentKey.objects.create(key="key-a", description="Key A")
        EnrollmentKey.objects.create(key="key-b", description="Key B", is_active=False)
        resp = self.client.get("/api/v1/enrollment-keys/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["results"]), 2)

    def test_enrollment_key_str(self):
        ek = EnrollmentKey.objects.create(key="my-secret-key-123", is_active=True)
        self.assertIn("active", str(ek))


# ══════════════════════════════════════════════════════════════════════════
# Audit Log Tests (admin auth required)
# ══════════════════════════════════════════════════════════════════════════

class AuditLogTests(TestCase):
    def setUp(self):
        self.client = _admin_client()

    def test_create_audit_log_via_api_is_readonly(self):
        resp = self.client.post("/api/v1/audit-logs/", {
            "actor_type": "system", "actor_id": "sched",
            "action": "test", "resource_type": "task", "resource_id": "abc",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_list_audit_logs(self):
        AuditLog.objects.create(actor_type="system", actor_id="sched",
                                 action="task_assigned", resource_type="task")
        resp = self.client.get("/api/v1/audit-logs/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["results"]), 1)

    def test_filter_audit_logs_by_action(self):
        AuditLog.objects.create(actor_type="system", actor_id="s",
                                 action="task_assigned", resource_type="task")
        AuditLog.objects.create(actor_type="node", actor_id="n",
                                 action="heartbeat_received", resource_type="node")
        resp = self.client.get("/api/v1/audit-logs/?action=heartbeat_received")
        self.assertEqual(len(resp.data["results"]), 1)

    def test_audit_log_str(self):
        log = AuditLog.objects.create(actor_type="node", actor_id="n1",
                                       action="registered", resource_type="node", resource_id="r1")
        self.assertIn("[node]", str(log))

    def test_list_audit_logs_requires_admin(self):
        resp = APIClient().get("/api/v1/audit-logs/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ══════════════════════════════════════════════════════════════════════════
# Protocol Version Tests
# ══════════════════════════════════════════════════════════════════════════

class ProtocolVersionTests(TestCase):
    def setUp(self):
        self.client = _admin_client()

    def test_list_protocol_versions(self):
        ProtocolVersion.objects.create(version="1.0", is_active=True)
        ProtocolVersion.objects.create(version="2.0", is_active=False)
        resp = self.client.get("/api/v1/protocol-versions/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["results"]), 2)

    def test_protocol_version_str(self):
        pv = ProtocolVersion.objects.create(version="1.0", is_active=True)
        self.assertEqual(str(pv), "v1.0 (active)")


# ══════════════════════════════════════════════════════════════════════════
# Token Authentication Tests (Phase 6)
# ══════════════════════════════════════════════════════════════════════════

class TokenAuthTests(TestCase):
    """Verify the NodeTokenAuthentication backend works correctly."""

    def setUp(self):
        self.node = Node.objects.create(
            device_id="token-node", hostname="token-node",
            status=Node.Status.ACTIVE, token="valid-token",
        )

    def test_valid_token_authenticates(self):
        c = _authed_client(token="valid-token")
        resp = c.post(f"/api/v1/nodes/{self.node.id}/heartbeat/",
                       {"status": "idle"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_invalid_token_rejected(self):
        c = _authed_client(token="wrong-token")
        resp = c.post(f"/api/v1/nodes/{self.node.id}/heartbeat/",
                       {"status": "idle"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_token_rejected(self):
        c = APIClient()
        resp = c.post(f"/api/v1/nodes/{self.node.id}/heartbeat/",
                       {"status": "idle"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_offline_node_token_rejected(self):
        self.node.status = Node.Status.OFFLINE
        self.node.save()
        c = _authed_client(token="valid-token")
        resp = c.post(f"/api/v1/nodes/{self.node.id}/heartbeat/",
                       {"status": "idle"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ══════════════════════════════════════════════════════════════════════════
# Audit Log Helper Tests (Phase 6)
# ══════════════════════════════════════════════════════════════════════════

class AuditLogHelperTests(TestCase):
    """Verify the log_event helper writes correct entries."""

    def test_log_event_creates_entry(self):
        from security.auth import log_event
        log_event(
            actor_type="system", actor_id="test-runner",
            action="test.event", resource_type="test", resource_id="123",
            details={"key": "value"},
        )
        entry = AuditLog.objects.first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.action, "test.event")
        self.assertEqual(entry.resource_id, "123")
        self.assertEqual(entry.details, {"key": "value"})

    def test_log_event_multiple_entries(self):
        from security.auth import log_event
        log_event(actor_type="node", actor_id="a1", action="node.register", resource_type="node")
        log_event(actor_type="node", actor_id="a1", action="node.activate", resource_type="node")
        self.assertEqual(AuditLog.objects.count(), 2)


# ══════════════════════════════════════════════════════════════════════════
# Stale Node Detection Tests (Phase 6)
# ══════════════════════════════════════════════════════════════════════════

class StaleNodeDetectionTests(TestCase):
    """Verify the detect_stale_nodes management command."""

    def setUp(self):
        self.now = timezone.now()

    def _make_node(self, device_id, status, minutes_ago=None, has_task=False):
        last_hb = None
        if minutes_ago is not None:
            last_hb = self.now - timedelta(minutes=minutes_ago)
        node = Node.objects.create(
            device_id=device_id, hostname=f"{device_id}.local",
            status=status, last_heartbeat=last_hb,
        )
        if has_task:
            job = Job.objects.create(task_type="checksum")
            Task.objects.create(
                job=job, task_type="checksum",
                status=Task.Status.ASSIGNED, assigned_to=node,
            )
        return node

    def test_no_stale_nodes(self):
        """Fresh nodes should not be flagged."""
        self._make_node("fresh", Node.Status.IDLE, minutes_ago=1)
        out = StringIO()
        call_command("detect_stale_nodes", stdout=out, stderr=StringIO())
        self.assertIn("Found 0 stale node(s)", out.getvalue())

    def test_detects_stale_node(self):
        """Node with heartbeat >5 min ago should be detected."""
        self._make_node("stale", Node.Status.IDLE, minutes_ago=10)
        out = StringIO()
        call_command("detect_stale_nodes", stdout=out, stderr=StringIO())
        self.assertIn("Found 1 stale node(s)", out.getvalue())

    def test_marks_stale_node_offline(self):
        """Stale node should be marked offline."""
        node = self._make_node("stale2", Node.Status.BUSY, minutes_ago=10)
        call_command("detect_stale_nodes", stdout=StringIO(), stderr=StringIO())
        node.refresh_from_db()
        self.assertEqual(node.status, Node.Status.OFFLINE)

    def test_reassigns_tasks(self):
        """Tasks assigned to stale node should be returned to queued."""
        node = self._make_node("stale3", Node.Status.BUSY, minutes_ago=10, has_task=True)
        task = Task.objects.get(assigned_to=node)
        call_command("detect_stale_nodes", stdout=StringIO(), stderr=StringIO())
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.QUEUED)
        self.assertIsNone(task.assigned_to)

    def test_ignores_offline_nodes(self):
        """Already-offline nodes should be ignored."""
        self._make_node("already-offline", Node.Status.OFFLINE, minutes_ago=10)
        out = StringIO()
        call_command("detect_stale_nodes", stdout=out, stderr=StringIO())
        self.assertIn("Found 0 stale node(s)", out.getvalue())

    def test_dry_run_does_not_modify(self):
        """--dry-run should report without making changes."""
        node = self._make_node("dry", Node.Status.IDLE, minutes_ago=10, has_task=True)
        out = StringIO()
        call_command("detect_stale_nodes", dry_run=True, stdout=out, stderr=StringIO())
        node.refresh_from_db()
        self.assertEqual(node.status, Node.Status.IDLE)  # unchanged
        self.assertIn("Dry-run", out.getvalue())

    def test_creates_audit_log(self):
        """Stale detection should write audit log entries."""
        node = self._make_node("audit-stale", Node.Status.BUSY, minutes_ago=10, has_task=True)
        call_command("detect_stale_nodes", stdout=StringIO(), stderr=StringIO())
        self.assertTrue(AuditLog.objects.filter(action="node.timeout").exists())
        self.assertTrue(AuditLog.objects.filter(action="task.reassign").exists())

    def test_custom_max_age(self):
        """--max-age should be configurable."""
        self._make_node("slightly-stale", Node.Status.IDLE, minutes_ago=8)
        out = StringIO()
        # With default 300s (5 min), this node (8 min) is stale
        # With --max-age 600 (10 min), it's not stale
        call_command("detect_stale_nodes", max_age=600, stdout=out, stderr=StringIO())
        self.assertIn("Found 0 stale node(s)", out.getvalue())
