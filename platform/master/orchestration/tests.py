"""
Tests for the orchestration app — job/task lifecycle, assignment, and result
submission, updated for Phase 6 auth enforcement.
"""

from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APIClient

from nodes.models import Node

from .models import Job, Task, TaskAssignment, TaskResult


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_node(token="orch-token", device_id="orch-node", **kw) -> Node:
    defaults = dict(device_id=device_id, hostname=f"{device_id}.local",
                    status=Node.Status.ACTIVE, token=token)
    defaults.update(kw)
    return Node.objects.create(**defaults)


def _authed_client(token="orch-token") -> APIClient:
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

class JobModelTests(TestCase):
    def test_job_creation(self):
        job = Job.objects.create(
            task_type="file_processing",
            input_payload={"files": ["/tmp/a.txt"]},
        )
        self.assertEqual(str(job), f"Job {job.id} — pending")
        self.assertEqual(job.status, "pending")


class TaskModelTests(TestCase):
    def test_task_creation(self):
        job = Job.objects.create(task_type="checksum")
        task = Task.objects.create(job=job, task_type="checksum", max_retries=5)
        self.assertEqual(str(task), f"Task {task.id} — pending")
        self.assertEqual(task.retry_count, 0)


# ══════════════════════════════════════════════════════════════════════════
# Task API Tests
# ══════════════════════════════════════════════════════════════════════════

class TaskAPITests(TestCase):
    def setUp(self):
        self.token = "task-token"
        self.node = _make_node(token=self.token, device_id="task-worker")
        self.job = Job.objects.create(
            task_type="file_processing", status=Job.Status.ACTIVE,
            input_payload={"operation": "compress"},
        )
        self.task = Task.objects.create(
            job=self.job, task_type="file_processing",
            status=Task.Status.PENDING, payload={"files": ["test.txt"]},
        )

    # ── Admin-only endpoints ────────────────────────────────────────

    def test_list_tasks_requires_admin(self):
        resp = APIClient().get("/api/v1/tasks/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_tasks_as_admin(self):
        admin = _admin_client()
        resp = admin.get("/api/v1/tasks/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_filter_tasks_by_status(self):
        Task.objects.create(job=self.job, task_type="checksum", status=Task.Status.COMPLETED)
        admin = _admin_client()
        resp = admin.get("/api/v1/tasks/?status=pending")
        self.assertEqual(len(resp.data["results"]), 1)

    def test_create_job_requires_admin(self):
        c = APIClient()
        resp = c.post("/api/v1/jobs/", {"task_type": "checksum", "input_payload": {}}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    # ── Agent-facing endpoints (require Bearer token) ───────────────

    def test_assign_requires_token(self):
        c = APIClient()
        resp = c.get(f"/api/v1/tasks/assign/?node_id={self.node.id}")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_assign_task(self):
        c = _authed_client(token=self.token)
        resp = c.get(f"/api/v1/tasks/assign/?node_id={self.node.id}")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("task_id", resp.data)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "assigned")
        self.assertEqual(self.task.assigned_to, self.node)
        self.assertEqual(TaskAssignment.objects.filter(task=self.task, node=self.node).count(), 1)

    def test_assign_no_tasks_available(self):
        self.task.status = Task.Status.ASSIGNED; self.task.save()
        c = _authed_client(token=self.token)
        resp = c.get(f"/api/v1/tasks/assign/?node_id={self.node.id}")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_assign_to_nonexistent_node(self):
        c = _authed_client(token=self.token)
        resp = c.get("/api/v1/tasks/assign/?node_id=00000000-0000-0000-0000-000000000000")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_assign_creates_audit_log(self):
        from security.models import AuditLog
        c = _authed_client(token=self.token)
        c.get(f"/api/v1/tasks/assign/?node_id={self.node.id}")
        self.assertTrue(AuditLog.objects.filter(action="task.assign").exists())

    def test_submit_result_requires_token(self):
        c = APIClient()
        self.task.status = Task.Status.ASSIGNED; self.task.save()
        resp = c.post(f"/api/v1/tasks/{self.task.id}/result/",
                       {"status": "completed"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_submit_result_completed(self):
        self.task.status = Task.Status.ASSIGNED; self.task.save()
        c = _authed_client(token=self.token)
        payload = {
            "status": "completed", "output": {"output_path": "/tmp/result.txt"},
            "metrics": {"duration_seconds": 12.5},
        }
        resp = c.post(f"/api/v1/tasks/{self.task.id}/result/", payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["accepted"])
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "completed")
        self.assertTrue(TaskResult.objects.filter(task=self.task).exists())

    def test_submit_result_failed_with_retry(self):
        self.task.status = Task.Status.ASSIGNED
        self.task.max_retries = 3; self.task.save()
        c = _authed_client(token=self.token)
        resp = c.post(f"/api/v1/tasks/{self.task.id}/result/", {
            "status": "failed", "error": {"code": "EXECUTION_TIMEOUT", "message": "Timed out"},
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["next_action"], "retry")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "retry")
        self.assertEqual(self.task.retry_count, 1)

    def test_submit_result_failed_exhausted_retries(self):
        self.task.status = Task.Status.ASSIGNED
        self.task.max_retries = 0; self.task.save()
        c = _authed_client(token=self.token)
        resp = c.post(f"/api/v1/tasks/{self.task.id}/result/", {
            "status": "failed", "error": {"code": "INTERNAL_ERROR"},
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "failed")

    def test_submit_result_invalid_status(self):
        self.task.status = Task.Status.ASSIGNED; self.task.save()
        c = _authed_client(token=self.token)
        resp = c.post(f"/api/v1/tasks/{self.task.id}/result/",
                       {"status": "unknown"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_submit_result_already_completed(self):
        self.task.status = Task.Status.COMPLETED; self.task.save()
        TaskResult.objects.create(task=self.task, status="completed")
        c = _authed_client(token=self.token)
        resp = c.post(f"/api/v1/tasks/{self.task.id}/result/",
                       {"status": "completed", "output": {}}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_submit_result_writes_audit_log(self):
        from security.models import AuditLog
        self.task.status = Task.Status.ASSIGNED; self.task.save()
        c = _authed_client(token=self.token)
        c.post(f"/api/v1/tasks/{self.task.id}/result/",
                {"status": "completed", "output": {}}, format="json")
        self.assertTrue(AuditLog.objects.filter(action="task.completed").exists())
