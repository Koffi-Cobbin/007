"""
Tests for the nodes app — device management, cluster operations, and
Phase 6 auth enforcement.
"""

from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from rest_framework import status
from rest_framework.test import APIClient

from django.contrib.auth.models import User

from security.models import AuditLog, EnrollmentKey

from .models import Cluster, Node, NodeCapability, NodeHeartbeat


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_node(token="test-token", device_id="test-node", **kw) -> Node:
    defaults = dict(device_id=device_id, hostname=f"{device_id}.local",
                    status=Node.Status.ACTIVE, token=token)
    defaults.update(kw)
    return Node.objects.create(**defaults)


def _authed_client(token="test-token") -> APIClient:
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return c


def _admin_client() -> APIClient:
    User.objects.create_superuser("admin", "admin@test.com", "password")
    c = APIClient()
    c.login(username="admin", password="password")
    return c


# ══════════════════════════════════════════════════════════════════════════
# Model Tests
# ══════════════════════════════════════════════════════════════════════════

class NodeModelTests(TestCase):
    def test_node_creation(self):
        node = Node.objects.create(
            device_id="test-device-001", hostname="node-1",
            platform="linux", status=Node.Status.ACTIVE,
        )
        self.assertEqual(str(node), "node-1 (active)")
        self.assertEqual(node.status, "active")


class NodeCapabilityModelTests(TestCase):
    def test_capability_creation(self):
        node = Node.objects.create(device_id="cap-test")
        cap = NodeCapability.objects.create(
            node=node, cpu_cores=12, memory_mb=16068, os_family="windows",
            workload_types=["file_processing", "checksum"],
        )
        self.assertIn("file_processing", cap.workload_types)


class ClusterModelTests(TestCase):
    def test_cluster_creation(self):
        cluster = Cluster.objects.create(name="test-cluster")
        self.assertEqual(str(cluster), "test-cluster (master: None)")

    def test_cluster_default_discovery_port(self):
        cluster = Cluster.objects.create(name="disc-cluster")
        self.assertEqual(cluster.discovery_port, 42069)


# ══════════════════════════════════════════════════════════════════════════
# Auth Enforcement Tests  (Phase 6)
# ══════════════════════════════════════════════════════════════════════════

class AuthEnforcementTests(TestCase):
    """Verifies that agent endpoints require a valid Bearer token."""

    def setUp(self):
        self.node = _make_node()
        self.admin = _admin_client()

    def test_register_no_token_required(self):
        """Registration uses enrollment keys, not bearer tokens."""
        EnrollmentKey.objects.create(key="ek", is_active=True)
        c = APIClient()
        resp = c.post("/api/v1/nodes/register/", {
            "device_id": "new-node", "enrollment_key": "ek",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_heartbeat_requires_token(self):
        c = APIClient()  # no token
        resp = c.post(f"/api/v1/nodes/{self.node.id}/heartbeat/",
                       {"status": "idle"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_activate_requires_token(self):
        c = APIClient()
        resp = c.put(f"/api/v1/nodes/{self.node.id}/activate/",
                      {"status": "active"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_health_requires_token(self):
        c = APIClient()
        resp = c.get(f"/api/v1/nodes/{self.node.id}/health/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_invalid_token_returns_403(self):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer invalid-token")
        resp = c.post(f"/api/v1/nodes/{self.node.id}/heartbeat/",
                       {"status": "idle"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_offline_node_token_rejected(self):
        offline = _make_node(device_id="offline-node", token="offline-tok",
                              status=Node.Status.OFFLINE)
        c = _authed_client(token="offline-tok")
        resp = c.post(f"/api/v1/nodes/{offline.id}/heartbeat/",
                       {"status": "idle"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_nodes_requires_admin(self):
        c = APIClient()
        resp = c.get("/api/v1/nodes/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_nodes_works_for_admin(self):
        resp = self.admin.get("/api/v1/nodes/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


# ══════════════════════════════════════════════════════════════════════════
# Registration API Tests (no auth — enrollment key based)
# ══════════════════════════════════════════════════════════════════════════

class RegistrationAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.ek = EnrollmentKey.objects.create(key="test-key-123", is_active=True)

    def test_register_success(self):
        payload = {
            "device_id": "device-abc", "hostname": "test-node",
            "platform": "linux", "enrollment_key": "test-key-123",
            "agent_version": "1.0.0",
            "capabilities": {"cpu_cores": 8, "memory_mb": 16384, "os_family": "linux"},
        }
        resp = self.client.post("/api/v1/nodes/register/", payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("node_id", resp.data)
        self.assertTrue(Node.objects.filter(device_id="device-abc").exists())
        node = Node.objects.get(device_id="device-abc")
        self.assertEqual(node.capabilities.count(), 1)
        self.ek.refresh_from_db()
        self.assertFalse(self.ek.is_active)

    def test_register_invalid_key(self):
        resp = self.client.post("/api/v1/nodes/register/",
                                 {"device_id": "x", "enrollment_key": "bad"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_register_duplicate_device_id(self):
        Node.objects.create(device_id="dup-device")
        resp = self.client.post("/api/v1/nodes/register/",
                                 {"device_id": "dup-device", "enrollment_key": "test-key-123"},
                                 format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_creates_audit_log(self):
        self.client.post("/api/v1/nodes/register/", {
            "device_id": "audit-node", "enrollment_key": "test-key-123",
        }, format="json")
        self.assertTrue(AuditLog.objects.filter(action="node.register").exists())


# ══════════════════════════════════════════════════════════════════════════
# Node API Tests (authenticated — Bearer token)
# ══════════════════════════════════════════════════════════════════════════

class NodeAPITests(TestCase):
    def setUp(self):
        self.token = "node-token-456"
        self.node = _make_node(token=self.token, device_id="api-node")
        self.client = _authed_client(token=self.token)

    def test_activate(self):
        self.node.status = Node.Status.ENROLLING
        self.node.save()
        resp = self.client.put(f"/api/v1/nodes/{self.node.id}/activate/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.node.refresh_from_db()
        self.assertEqual(self.node.status, "active")

    def test_heartbeat(self):
        payload = {"status": "idle", "current_load": 0.25, "uptime_seconds": 3600}
        resp = self.client.post(f"/api/v1/nodes/{self.node.id}/heartbeat/",
                                 payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["accepted"])
        self.assertEqual(NodeHeartbeat.objects.filter(node=self.node).count(), 1)
        self.node.refresh_from_db()
        self.assertEqual(self.node.status, "idle")

    def test_heartbeat_does_not_change_status(self):
        self.node.status = Node.Status.BUSY
        self.node.save()
        payload = {"current_load": 0.9, "uptime_seconds": 7200}
        resp = self.client.post(f"/api/v1/nodes/{self.node.id}/heartbeat/",
                                 payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.node.refresh_from_db()
        self.assertEqual(self.node.status, "busy")


class HealthEndpointTests(TestCase):
    """Phase 6: GET /api/v1/nodes/{id}/health/"""

    def setUp(self):
        self.token = "health-token"
        self.node = _make_node(token=self.token, device_id="health-node")
        NodeCapability.objects.create(
            node=self.node, cpu_cores=8, memory_mb=16384,
            workload_types=["checksum"],
        )
        NodeHeartbeat.objects.create(
            node=self.node, current_load=0.15, status="idle",
            resources={"cpu_percent": 15, "memory_used_mb": 4096, "disk_free_mb": 80000},
            uptime_seconds=86400,
        )
        self.client = _authed_client(token=self.token)

    def test_health_returns_node_state(self):
        resp = self.client.get(f"/api/v1/nodes/{self.node.id}/health/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["device_id"], "health-node")
        self.assertEqual(resp.data["status"], "active")
        self.assertIn("current_load", resp.data)
        self.assertIn("uptime_seconds", resp.data)
        self.assertIn("tasks_completed", resp.data)
        self.assertIn("cluster_id", resp.data)

    def test_health_requires_auth(self):
        c = APIClient()
        resp = c.get(f"/api/v1/nodes/{self.node.id}/health/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ══════════════════════════════════════════════════════════════════════════
# Cluster API Tests (admin auth required since ClusterViewSet uses ModelViewSet)
# ══════════════════════════════════════════════════════════════════════════

class ClusterAPITests(TestCase):
    def setUp(self):
        self.admin = _admin_client()
        self.cluster = Cluster.objects.create(name="test-cluster")
        self.node = Node.objects.create(
            device_id="cluster-node", hostname="node-1", status=Node.Status.ACTIVE,
        )

    def test_list_clusters(self):
        resp = self.admin.get("/api/v1/clusters/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["results"]), 1)

    def test_create_cluster(self):
        resp = self.admin.post("/api/v1/clusters/", {"name": "new-cluster"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_cluster_detail_includes_members(self):
        self.node.cluster = self.cluster; self.node.save()
        resp = self.admin.get(f"/api/v1/clusters/{self.cluster.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("member_count", resp.data)
        self.assertEqual(resp.data["member_count"], 1)

    def test_join_cluster(self):
        resp = self.admin.post(
            f"/api/v1/clusters/{self.cluster.id}/join/",
            {"node_id": str(self.node.id)}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "joined")

    def test_join_nonexistent_node(self):
        resp = self.admin.post(
            f"/api/v1/clusters/{self.cluster.id}/join/",
            {"node_id": "00000000-0000-0000-0000-000000000000"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_leave_cluster(self):
        self.node.cluster = self.cluster; self.node.save()
        resp = self.admin.post(
            f"/api/v1/clusters/{self.cluster.id}/leave/",
            {"node_id": str(self.node.id)}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "left")

    def test_leave_clears_master(self):
        self.node.cluster = self.cluster; self.node.save()
        self.cluster.master_node = self.node; self.cluster.save()
        self.admin.post(
            f"/api/v1/clusters/{self.cluster.id}/leave/",
            {"node_id": str(self.node.id)}, format="json",
        )
        self.cluster.refresh_from_db()
        self.assertIsNone(self.cluster.master_node)

    def test_members_list(self):
        n2 = Node.objects.create(device_id="node-b")
        self.node.cluster = self.cluster; self.node.save()
        n2.cluster = self.cluster; n2.save()
        resp = self.admin.get(f"/api/v1/clusters/{self.cluster.id}/members/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 2)

    def test_elect_master(self):
        self.node.cluster = self.cluster; self.node.save()
        resp = self.admin.post(
            f"/api/v1/clusters/{self.cluster.id}/elect-master/",
            {"node_id": str(self.node.id)}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.cluster.refresh_from_db()
        self.assertEqual(self.cluster.master_node_id, self.node.id)

    def test_elect_master_node_not_in_cluster(self):
        outside = Node.objects.create(device_id="outside")
        resp = self.admin.post(
            f"/api/v1/clusters/{self.cluster.id}/elect-master/",
            {"node_id": str(outside.id)}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)


# ══════════════════════════════════════════════════════════════════════════
# Discovery API Tests (no auth — public beacon)
# ══════════════════════════════════════════════════════════════════════════

class DiscoveryAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_discover_empty(self):
        resp = self.client.get("/api/v1/discover/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["servers"], [])

    def test_discover_with_master(self):
        node = Node.objects.create(device_id="master-node")
        cluster = Cluster.objects.create(name="prod", master_node=node)
        node.cluster = cluster; node.save()
        resp = self.client.get("/api/v1/discover/")
        self.assertEqual(len(resp.data["servers"]), 1)


# ══════════════════════════════════════════════════════════════════════════
# Audit Log Tests (Phase 6)
# ══════════════════════════════════════════════════════════════════════════

class AuditLogIntegrationTests(TestCase):
    """Verify audit logs are written by key events."""

    def setUp(self):
        self.token = "audit-token"
        self.node = _make_node(token=self.token, device_id="audit-node")
        EnrollmentKey.objects.create(key="audit-ek", is_active=True)

    def test_register_writes_audit_log(self):
        APIClient().post("/api/v1/nodes/register/", {
            "device_id": "audit-target", "enrollment_key": "audit-ek",
        }, format="json")
        self.assertTrue(AuditLog.objects.filter(action="node.register").exists())

    def test_activate_writes_audit_log(self):
        self.node.status = Node.Status.ENROLLING; self.node.save()
        c = _authed_client(token=self.token)
        c.put(f"/api/v1/nodes/{self.node.id}/activate/")
        self.assertTrue(AuditLog.objects.filter(action="node.activate").exists())
