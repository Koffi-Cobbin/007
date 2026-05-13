"""
Tests for the Workload Registry and Plugin System (Phase 7).

Covers WorkloadType model, CRUD API, schema validation on job creation,
and the resource-aware scheduler integration.
"""

from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APIClient

from .models import Job, Task, WorkloadType
from .views import _validate_payload_against_schema


# ── Helpers ──────────────────────────────────────────────────────────────

def _admin_client() -> APIClient:
    User.objects.create_superuser("admin", "admin@test.com", "password")
    c = APIClient()
    c.login(username="admin", password="password")
    return c


# ══════════════════════════════════════════════════════════════════════════
# WorkloadType Model Tests
# ══════════════════════════════════════════════════════════════════════════

class WorkloadTypeModelTests(TestCase):
    def test_create_workload_type(self):
        wt = WorkloadType.objects.create(
            name="custom_processor",
            description="Custom data processor",
            input_schema={
                "required": ["files", "operation"],
                "properties": {
                    "files": {"type": "array"},
                    "operation": {"type": "string"},
                },
            },
            version="2.1.0",
            author="test-dev",
        )
        self.assertEqual(str(wt), "custom_processor v2.1.0")
        self.assertTrue(wt.is_active)

    def test_default_version(self):
        wt = WorkloadType.objects.create(name="minimal")
        self.assertEqual(wt.version, "1.0.0")

    def test_active_filter(self):
        WorkloadType.objects.create(name="active-one")
        WorkloadType.objects.create(name="inactive-one", is_active=False)
        active = WorkloadType.objects.filter(is_active=True)
        self.assertEqual(active.count(), 1)


# ══════════════════════════════════════════════════════════════════════════
# WorkloadType API Tests
# ══════════════════════════════════════════════════════════════════════════

class WorkloadTypeAPITests(TestCase):
    def setUp(self):
        self.admin = _admin_client()
        WorkloadType.objects.create(
            name="checksum", description="Verify file integrity",
            input_schema={"required": ["files"]},
        )
        WorkloadType.objects.create(
            name="custom_test", description="A test type",
            is_active=False,
        )

    def test_list_active_types(self):
        """GET /api/v1/workload-types/ returns only active types."""
        resp = APIClient().get("/api/v1/workload-types/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [wt["name"] for wt in resp.data["results"]]
        self.assertIn("checksum", names)
        self.assertNotIn("custom_test", names)

    def test_detail_by_name(self):
        resp = APIClient().get("/api/v1/workload-types/checksum/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["description"], "Verify file integrity")
        self.assertIn("input_schema", resp.data)

    def test_detail_not_found(self):
        resp = APIClient().get("/api/v1/workload-types/nonexistent/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_requires_admin(self):
        resp = APIClient().post("/api/v1/workload-types/",
                                 {"name": "hacker-type"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_as_admin(self):
        resp = self.admin.post("/api/v1/workload-types/", {
            "name": "new_processor",
            "description": "A brand new workload type",
            "input_schema": {
                "required": ["input_path"],
                "properties": {"input_path": {"type": "string"}},
            },
            "author": "plugin-team",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(WorkloadType.objects.filter(name="new_processor").exists())


# ══════════════════════════════════════════════════════════════════════════
# Schema Validation Tests
# ══════════════════════════════════════════════════════════════════════════

class SchemaValidationUnitTests(TestCase):
    """Unit tests for _validate_payload_against_schema."""

    def test_empty_schema_no_errors(self):
        errors = _validate_payload_against_schema({"x": 1}, {})
        self.assertEqual(errors, [])

    def test_required_field_present(self):
        schema = {"required": ["name"], "properties": {"name": {"type": "string"}}}
        errors = _validate_payload_against_schema({"name": "hello"}, schema)
        self.assertEqual(errors, [])

    def test_required_field_missing(self):
        schema = {"required": ["name"], "properties": {"name": {"type": "string"}}}
        errors = _validate_payload_against_schema({}, schema)
        self.assertIn("name", errors[0])

    def test_type_mismatch_array(self):
        schema = {"properties": {"files": {"type": "array"}}}
        errors = _validate_payload_against_schema({"files": "not-a-list"}, schema)
        self.assertIn("array", errors[0])

    def test_type_mismatch_integer(self):
        schema = {"properties": {"count": {"type": "integer"}}}
        errors = _validate_payload_against_schema({"count": "seven"}, schema)
        self.assertIn("integer", errors[0])

    def test_type_mismatch_number(self):
        schema = {"properties": {"value": {"type": "number"}}}
        errors = _validate_payload_against_schema({"value": "NaN"}, schema)
        self.assertIn("number", errors[0])

    def test_valid_number_passes(self):
        schema = {"properties": {"value": {"type": "number"}}}
        errors = _validate_payload_against_schema({"value": 42.5}, schema)
        self.assertEqual(errors, [])

    def test_valid_integer_passes(self):
        schema = {"properties": {"count": {"type": "integer"}}}
        errors = _validate_payload_against_schema({"count": 7}, schema)
        self.assertEqual(errors, [])


class SchemaValidationIntegrationTests(TestCase):
    """Schema validation triggers on job creation via the API."""

    def setUp(self):
        self.admin = _admin_client()
        WorkloadType.objects.create(
            name="validated_type",
            is_active=True,
            input_schema={
                "required": ["files", "operation"],
                "properties": {
                    "files": {"type": "array"},
                    "operation": {"type": "string"},
                },
            },
        )

    def test_valid_payload_creates_job(self):
        resp = self.admin.post("/api/v1/jobs/", {
            "task_type": "validated_type",
            "input_payload": {"files": ["a.txt"], "operation": "copy"},
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_missing_required_field_returns_422(self):
        resp = self.admin.post("/api/v1/jobs/", {
            "task_type": "validated_type",
            "input_payload": {"files": ["a.txt"]},  # missing "operation"
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("input_payload", resp.data)

    def test_wrong_type_returns_400(self):
        resp = self.admin.post("/api/v1/jobs/", {
            "task_type": "validated_type",
            "input_payload": {"files": "not-a-list", "operation": "copy"},
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unregistered_type_skips_validation(self):
        """Job types not in the WorkloadType registry pass through."""
        resp = self.admin.post("/api/v1/jobs/", {
            "task_type": "totally_unknown_type",
            "input_payload": {"anything": "goes"},
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)


# ══════════════════════════════════════════════════════════════════════════
# Resource Requirements Tests (Phase 7)
# ══════════════════════════════════════════════════════════════════════════

class TaskResourceRequirementsTests(TestCase):
    """Verify the required_resources field on Task."""

    def test_default_is_empty_dict(self):
        task = Task.objects.create(
            job=Job.objects.create(task_type="checksum"),
            task_type="checksum",
        )
        self.assertEqual(task.required_resources, {})

    def test_can_set_resource_requirements(self):
        task = Task.objects.create(
            job=Job.objects.create(task_type="heavy_compute"),
            task_type="heavy_compute",
            required_resources={"min_cpu_cores": 8, "min_memory_mb": 16384},
        )
        self.assertEqual(task.required_resources["min_cpu_cores"], 8)
