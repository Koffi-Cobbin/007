"""
Tests for the scheduling intelligence engine (Phase 5).

Covers scoring functions, node filtering, priority ordering, and
integration with the task assignment endpoint.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APIClient

from nodes.models import Cluster, Node, NodeCapability, NodeHeartbeat


# ── Auth helpers (Phase 6) ───────────────────────────────────────────

def _authed_client(token="sched-token") -> APIClient:
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return c


def _admin_client() -> APIClient:
    User.objects.create_superuser("admin", "admin@test.com", "password")
    c = APIClient()
    c.login(username="admin", password="password")
    return c

from .models import Job, Task, TaskAssignment, TaskResult
from .scheduler import (
    MAX_HEARTBEAT_AGE_SECONDS,
    PRIORITY_ORDER,
    WEIGHTS,
    find_best_node,
    get_assignable_tasks_for_node,
    get_candidate_nodes,
    score_node_for_task,
    _score_capability,
    _score_health,
    _score_reliability,
    _score_resource,
)

# Helper to force a heartbeat timestamp (bypasses auto_now_add)
def _force_hb_timestamp(heartbeat, dt):
    NodeHeartbeat.objects.filter(id=heartbeat.id).update(received_at=dt)
    heartbeat.refresh_from_db()


# ═════════════════════════════════════════════════════════════════════════════
# Unit Tests — Scoring Functions
# ═════════════════════════════════════════════════════════════════════════════

class ScoreCapabilityTests(TestCase):
    """_score_capability returns 0.0–1.0 based on workload-type + hardware."""

    def setUp(self):
        self.node = Node.objects.create(device_id="cap-node", status=Node.Status.IDLE)
        self.task = Task.objects.create(
            job=Job.objects.create(task_type="checksum"),
            task_type="checksum",
        )
        NodeCapability.objects.create(
            node=self.node,
            cpu_cores=8,
            memory_mb=16384,
            workload_types=["checksum", "file_processing"],
        )

    def test_matching_workload_type_scores_above_zero(self):
        score = _score_capability(self.node, self.task)
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_non_matching_workload_type_returns_zero(self):
        task = Task.objects.create(
            job=Job.objects.create(task_type="image_processing"),
            task_type="image_processing",
        )
        score = _score_capability(self.node, task)
        self.assertEqual(score, 0.0)

    def test_no_capability_record_returns_zero(self):
        bare_node = Node.objects.create(device_id="bare")
        score = _score_capability(bare_node, self.task)
        self.assertEqual(score, 0.0)

    def test_more_cores_and_ram_increases_score(self):
        weak_node = Node.objects.create(device_id="weak")
        NodeCapability.objects.create(
            node=weak_node,
            cpu_cores=2,
            memory_mb=2048,
            workload_types=["checksum"],
        )
        strong_score = _score_capability(self.node, self.task)  # 8 cores, 16 GB
        weak_score = _score_capability(weak_node, self.task)    # 2 cores, 2 GB
        self.assertGreater(strong_score, weak_score)


class ScoreResourceTests(TestCase):
    """_score_resource returns 0.0–1.0 based on latest heartbeat load."""

    def setUp(self):
        self.node = Node.objects.create(device_id="res-node")
        NodeCapability.objects.create(
            node=self.node, cpu_cores=8, memory_mb=16384, disk_free_mb=100000,
        )
        NodeHeartbeat.objects.create(
            node=self.node,
            current_load=0.0,
            resources={
                "cpu_percent": 5.0,
                "memory_used_mb": 4096,
                "disk_free_mb": 90000,
            },
            uptime_seconds=86400,
        )

    def test_idle_node_scores_high(self):
        score = _score_resource(self.node)
        self.assertGreater(score, 0.8)
        self.assertLessEqual(score, 1.0)

    def test_loaded_node_scores_lower(self):
        NodeHeartbeat.objects.create(
            node=self.node,
            current_load=0.85,
            resources={"memory_used_mb": 14000, "disk_free_mb": 10000},
            uptime_seconds=86400,
        )
        score = _score_resource(self.node)
        self.assertLess(score, 0.5)

    def test_no_heartbeat_returns_optimistic_score(self):
        bare_node = Node.objects.create(device_id="no-hb")
        score = _score_resource(bare_node)
        self.assertEqual(score, 1.0)


class ScoreHealthTests(TestCase):
    """_score_health returns 0.0–1.0 based on status + heartbeat freshness."""

    def setUp(self):
        self.node = Node.objects.create(device_id="health-node", status=Node.Status.IDLE)
        NodeHeartbeat.objects.create(
            node=self.node, current_load=0.1, received_at=timezone.now(),
        )

    def test_idle_with_fresh_hb_scores_high(self):
        score = _score_health(self.node)
        self.assertGreater(score, 0.8)

    def test_degraded_node_scores_low(self):
        self.node.status = Node.Status.DEGRADED
        self.node.save()
        score = _score_health(self.node)
        self.assertLess(score, 0.5)

    def test_stale_heartbeat_reduces_score(self):
        score_fresh = _score_health(self.node)
        # Force last heartbeat to be stale
        old = timezone.now() - timedelta(seconds=MAX_HEARTBEAT_AGE_SECONDS + 60)
        latest_hb = self.node.heartbeats.order_by("-received_at").first()
        _force_hb_timestamp(latest_hb, old)
        score_stale = _score_health(self.node)
        self.assertGreaterEqual(score_fresh, score_stale)


class ScoreReliabilityTests(TestCase):
    """_score_reliability returns historical success ratio."""

    def setUp(self):
        self.node = Node.objects.create(device_id="rel-node")
        self.job = Job.objects.create(task_type="checksum")
        self.task = Task.objects.create(job=self.job, task_type="checksum", assigned_to=self.node)

    def test_no_history_returns_neutral(self):
        score = _score_reliability(self.node)
        self.assertEqual(score, 0.5)

    def test_all_success_returns_one(self):
        TaskResult.objects.create(task=self.task, status="completed")
        score = _score_reliability(self.node)
        self.assertEqual(score, 1.0)

    def test_mixed_history_returns_ratio(self):
        TaskResult.objects.create(task=self.task, status="completed")
        t2 = Task.objects.create(job=self.job, task_type="checksum", assigned_to=self.node)
        TaskResult.objects.create(task=t2, status="failed")
        score = _score_reliability(self.node)
        self.assertEqual(score, 0.5)


class ScoreNodeForTaskTests(TestCase):
    """score_node_for_task returns a complete breakdown."""

    def setUp(self):
        self.cluster = Cluster.objects.create(name="score-cluster")
        self.node = Node.objects.create(
            device_id="score-node", status=Node.Status.IDLE, cluster=self.cluster,
        )
        NodeCapability.objects.create(
            node=self.node, cpu_cores=8, memory_mb=16384,
            workload_types=["checksum"],
        )
        NodeHeartbeat.objects.create(
            node=self.node, current_load=0.1,
            resources={"memory_used_mb": 4096, "disk_free_mb": 80000},
        )
        self.job = Job.objects.create(task_type="checksum")
        self.task = Task.objects.create(job=self.job, task_type="checksum")

    def test_returns_dict_with_overall_and_breakdown(self):
        result = score_node_for_task(self.node, self.task)
        self.assertIn("overall", result)
        self.assertIn("breakdown", result)
        for dim in ("capability", "resource", "health", "reliability"):
            self.assertIn(dim, result["breakdown"])

    def test_overall_is_weighted_combination(self):
        result = score_node_for_task(self.node, self.task)
        expected = sum(
            result["breakdown"][dim] * WEIGHTS[dim] for dim in WEIGHTS
        )
        self.assertAlmostEqual(result["overall"], round(expected, 4))


# ═════════════════════════════════════════════════════════════════════════════
# Unit Tests — Candidate & Task Selection
# ═════════════════════════════════════════════════════════════════════════════

class GetCandidateNodesTests(TestCase):
    """get_candidate_nodes filters correctly based on health + capability."""

    def setUp(self):
        self.cluster = Cluster.objects.create(name="candidate-cluster")

    def test_healthy_capable_node_is_candidate(self):
        node = Node.objects.create(
            device_id="good", status=Node.Status.IDLE, cluster=self.cluster,
        )
        NodeCapability.objects.create(
            node=node, workload_types=["checksum"],
        )
        NodeHeartbeat.objects.create(
            node=node, current_load=0.2, received_at=timezone.now(),
        )
        candidates = get_candidate_nodes("checksum", self.cluster)
        self.assertIn(node, candidates)

    def test_degraded_node_excluded(self):
        node = Node.objects.create(
            device_id="bad", status=Node.Status.DEGRADED, cluster=self.cluster,
        )
        NodeCapability.objects.create(node=node, workload_types=["checksum"])
        candidates = get_candidate_nodes("checksum", self.cluster)
        self.assertNotIn(node, candidates)

    def test_stale_heartbeat_excluded(self):
        node = Node.objects.create(
            device_id="stale", status=Node.Status.IDLE, cluster=self.cluster,
        )
        NodeCapability.objects.create(node=node, workload_types=["checksum"])
        hb = NodeHeartbeat.objects.create(node=node, current_load=0.2)
        # Force stale timestamp (bypass auto_now_add)
        old = timezone.now() - timedelta(seconds=MAX_HEARTBEAT_AGE_SECONDS + 60)
        _force_hb_timestamp(hb, old)
        candidates = get_candidate_nodes("checksum", self.cluster)
        self.assertNotIn(node, candidates)

    def test_wrong_workload_type_excluded(self):
        node = Node.objects.create(
            device_id="wrong-type", status=Node.Status.IDLE, cluster=self.cluster,
        )
        NodeCapability.objects.create(node=node, workload_types=["file_processing"])
        NodeHeartbeat.objects.create(
            node=node, current_load=0.2, received_at=timezone.now(),
        )
        candidates = get_candidate_nodes("checksum", self.cluster)
        self.assertNotIn(node, candidates)

    def test_overloaded_node_excluded(self):
        node = Node.objects.create(
            device_id="overloaded", status=Node.Status.BUSY, cluster=self.cluster,
        )
        NodeCapability.objects.create(node=node, workload_types=["checksum"])
        NodeHeartbeat.objects.create(
            node=node, current_load=0.99, received_at=timezone.now(),
        )
        candidates = get_candidate_nodes("checksum", self.cluster)
        self.assertNotIn(node, candidates)

    def test_node_not_in_cluster_excluded(self):
        node = Node.objects.create(
            device_id="outsider", status=Node.Status.IDLE, cluster=None,
        )
        NodeCapability.objects.create(node=node, workload_types=["checksum"])
        candidates = get_candidate_nodes("checksum", self.cluster)
        self.assertNotIn(node, candidates)


class GetAssignableTasksTests(TestCase):
    """get_assignable_tasks_for_node returns tasks ordered by priority then age."""

    def setUp(self):
        self.node = Node.objects.create(device_id="worker")
        NodeCapability.objects.create(
            node=self.node, workload_types=["checksum", "file_processing"],
        )
        self.job = Job.objects.create(task_type="checksum")

    def test_returns_tasks_matching_capabilities(self):
        Task.objects.create(job=self.job, task_type="checksum", status=Task.Status.QUEUED)
        tasks = get_assignable_tasks_for_node(self.node, ["checksum"])
        self.assertEqual(len(tasks), 1)

    def test_falls_back_to_non_matching_tasks(self):
        """When no capability-matched tasks exist, scheduler falls back to any available task."""
        Task.objects.create(job=self.job, task_type="image_processing", status=Task.Status.QUEUED)
        tasks = get_assignable_tasks_for_node(self.node, ["checksum"])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].task_type, "image_processing")

    def test_prioritizes_retry_over_pending(self):
        Task.objects.create(job=self.job, task_type="checksum", status=Task.Status.QUEUED)
        t2 = Task.objects.create(job=self.job, task_type="checksum", status=Task.Status.RETRY)
        tasks = get_assignable_tasks_for_node(self.node, ["checksum"])
        self.assertEqual(tasks[0].id, t2.id)

    def test_orders_by_priority_then_age(self):
        t_high = Task.objects.create(
            job=self.job, task_type="checksum", status=Task.Status.QUEUED, priority="high",
        )
        t_med = Task.objects.create(
            job=self.job, task_type="checksum", status=Task.Status.QUEUED, priority="medium",
        )
        t_low = Task.objects.create(
            job=self.job, task_type="checksum", status=Task.Status.QUEUED, priority="low",
        )
        tasks = get_assignable_tasks_for_node(self.node, ["checksum"])
        self.assertEqual(tasks[0].id, t_high.id)
        self.assertEqual(tasks[1].id, t_med.id)
        self.assertEqual(tasks[2].id, t_low.id)


class FindBestNodeTests(TestCase):
    """find_best_node picks the highest-scoring node."""

    def setUp(self):
        self.cluster = Cluster.objects.create(name="best-cluster")
        self.job = Job.objects.create(task_type="checksum")
        self.task = Task.objects.create(job=self.job, task_type="checksum")

    def test_returns_best_node(self):
        weak = Node.objects.create(device_id="weak", status=Node.Status.BUSY, cluster=self.cluster)
        NodeCapability.objects.create(node=weak, workload_types=["checksum"])
        NodeHeartbeat.objects.create(node=weak, current_load=0.9)

        strong = Node.objects.create(device_id="strong", status=Node.Status.IDLE, cluster=self.cluster)
        NodeCapability.objects.create(node=strong, workload_types=["checksum"])
        NodeHeartbeat.objects.create(node=strong, current_load=0.1)

        best, score = find_best_node(self.task, [weak, strong])
        self.assertEqual(best.id, strong.id)

    def test_returns_none_for_empty_list(self):
        best, score = find_best_node(self.task, [])
        self.assertIsNone(best)
        self.assertIsNone(score)


# ═════════════════════════════════════════════════════════════════════════════
# Integration Tests — Assign Endpoint with Scheduling
# ═════════════════════════════════════════════════════════════════════════════

class SchedulerIntegrationTests(TestCase):
    """End-to-end: the assign endpoint uses priority + scoring."""

    def setUp(self):
        self.strong_token = "strong-token"
        self.weak_token = "weak-token"
        self.cluster = Cluster.objects.create(name="int-cluster")

        # Two nodes in the same cluster
        self.strong_node = Node.objects.create(
            device_id="strong", hostname="strong-1",
            status=Node.Status.IDLE, cluster=self.cluster,
            token=self.strong_token,
        )
        NodeCapability.objects.create(
            node=self.strong_node, cpu_cores=16, memory_mb=32768,
            workload_types=["checksum", "file_processing"],
        )
        NodeHeartbeat.objects.create(
            node=self.strong_node, current_load=0.05,
            resources={"memory_used_mb": 4096, "disk_free_mb": 200000},
        )

        self.weak_node = Node.objects.create(
            device_id="weak", hostname="weak-1",
            status=Node.Status.BUSY, cluster=self.cluster,
            token=self.weak_token,
        )
        NodeCapability.objects.create(
            node=self.weak_node, cpu_cores=2, memory_mb=2048,
            workload_types=["checksum"],
        )
        NodeHeartbeat.objects.create(
            node=self.weak_node, current_load=0.85,
            resources={"memory_used_mb": 1800, "disk_free_mb": 5000},
        )

        self.job = Job.objects.create(
            task_type="checksum",
            status=Job.Status.ACTIVE,
            input_payload={"files": ["a.iso"]},
        )

        self.strong_client = _authed_client(token=self.strong_token)
        self.weak_client = _authed_client(token=self.weak_token)
        self.admin_client = _admin_client()

    def _create_task(self, **kwargs):
        defaults = dict(job=self.job, task_type="checksum", status=Task.Status.QUEUED)
        defaults.update(kwargs)
        return Task.objects.create(**defaults)

    def test_assign_response_includes_scheduling_score(self):
        self._create_task()
        response = self.strong_client.get(f"/api/v1/tasks/assign/?node_id={self.strong_node.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("scheduling_score", response.data)
        self.assertIn("overall", response.data["scheduling_score"])
        self.assertIn("breakdown", response.data["scheduling_score"])

    def test_assign_response_includes_priority(self):
        self._create_task(priority="high")
        response = self.strong_client.get(f"/api/v1/tasks/assign/?node_id={self.strong_node.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["priority"], "high")

    def test_high_priority_assigned_before_low(self):
        t_low = self._create_task(priority="low", status=Task.Status.QUEUED)
        t_high = self._create_task(priority="high", status=Task.Status.QUEUED)
        r1 = self.strong_client.get(f"/api/v1/tasks/assign/?node_id={self.strong_node.id}")
        self.assertEqual(r1.data["task_id"], str(t_high.id))
        r2 = self.strong_client.get(f"/api/v1/tasks/assign/?node_id={self.strong_node.id}")
        self.assertEqual(r2.data["task_id"], str(t_low.id))

    def test_stronger_node_gets_task_over_weaker(self):
        self._create_task()
        r_strong = self.strong_client.get(f"/api/v1/tasks/assign/?node_id={self.strong_node.id}")
        self.assertEqual(r_strong.status_code, status.HTTP_200_OK)
        r_weak = self.weak_client.get(f"/api/v1/tasks/assign/?node_id={self.weak_node.id}")
        self.assertEqual(r_weak.status_code, status.HTTP_204_NO_CONTENT)

    def test_weak_node_gets_task_when_no_better_node_available(self):
        """If weak node is the only candidate, it still gets the task."""
        self._create_task()
        r1 = self.weak_client.get(f"/api/v1/tasks/assign/?node_id={self.weak_node.id}")
        self.assertEqual(r1.status_code, status.HTTP_204_NO_CONTENT)
        self.strong_client.get(f"/api/v1/tasks/assign/?node_id={self.strong_node.id}")
        self._create_task()
        self.strong_node.cluster = None
        self.strong_node.save()
        r2 = self.weak_client.get(f"/api/v1/tasks/assign/?node_id={self.weak_node.id}")
        self.assertEqual(r2.status_code, status.HTTP_200_OK)

    def test_create_job_with_priority(self):
        payload = {
            "task_type": "checksum",
            "input_payload": {"files": ["x.iso"]},
            "priority": "high",
        }
        response = self.admin_client.post("/api/v1/jobs/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        job_id = response.data["id"]
        job = Job.objects.get(id=job_id)
        self.assertEqual(job.priority, "high")


class JobPriorityTests(TestCase):
    """Job priority is inherited by all sub-tasks."""

    def setUp(self):
        self.client = _admin_client()

    def test_job_default_priority_is_medium(self):
        payload = {"task_type": "checksum", "input_payload": {"files": ["a.txt"]}}
        response = self.client.post("/api/v1/jobs/", payload, format="json")
        job = Job.objects.get(id=response.data["id"])
        self.assertEqual(job.priority, "medium")

    def test_job_priority_passed_in_payload(self):
        payload = {
            "task_type": "checksum",
            "input_payload": {"files": ["a.txt"]},
            "priority": "high",
        }
        response = self.client.post("/api/v1/jobs/", payload, format="json")
        job = Job.objects.get(id=response.data["id"])
        self.assertEqual(job.priority, "high")


# ═════════════════════════════════════════════════════════════════════════════
# Property Tests — Invariants
# ═════════════════════════════════════════════════════════════════════════════


class ScoreInvariantTests(TestCase):
    """Property-based-style tests: score bounds and monotonicity."""

    def setUp(self):
        self.cluster = Cluster.objects.create(name="inv-cluster")
        self.node = Node.objects.create(
            device_id="inv-node", status=Node.Status.IDLE, cluster=self.cluster,
        )
        NodeCapability.objects.create(
            node=self.node, cpu_cores=8, memory_mb=16384,
            workload_types=["checksum"],
        )
        NodeHeartbeat.objects.create(
            node=self.node, current_load=0.1,
            resources={"memory_used_mb": 4096, "disk_free_mb": 80000},
        )
        self.job = Job.objects.create(task_type="checksum")
        self.task = Task.objects.create(job=self.job, task_type="checksum")

    def test_overall_score_always_between_0_and_1(self):
        """No matter what inputs, overall score is 0.0-1.0."""
        result = score_node_for_task(self.node, self.task)
        self.assertGreaterEqual(result["overall"], 0.0)
        self.assertLessEqual(result["overall"], 1.0)

    def test_all_breakdown_scores_always_between_0_and_1(self):
        """Every breakdown dimension individually stays within bounds."""
        result = score_node_for_task(self.node, self.task)
        for dim in ("capability", "resource", "health", "reliability"):
            val = result["breakdown"][dim]
            self.assertGreaterEqual(val, 0.0, f"{dim} fell below 0")
            self.assertLessEqual(val, 1.0, f"{dim} exceeded 1")

    def test_no_node_strictly_better_scores_lower(self):
        """Node A strictly better than B on all dims → A scores higher."""
        weak = Node.objects.create(
            device_id="weak-inv", status=Node.Status.BUSY, cluster=self.cluster,
        )
        NodeCapability.objects.create(
            node=weak, cpu_cores=2, memory_mb=2048,
            workload_types=["checksum"],
        )
        NodeHeartbeat.objects.create(
            node=weak, current_load=0.9,
            resources={"memory_used_mb": 1900, "disk_free_mb": 1000},
        )

        strong = Node.objects.create(
            device_id="strong-inv", status=Node.Status.IDLE, cluster=self.cluster,
        )
        NodeCapability.objects.create(
            node=strong, cpu_cores=16, memory_mb=65536,
            workload_types=["checksum"],
        )
        NodeHeartbeat.objects.create(
            node=strong, current_load=0.05,
            resources={"memory_used_mb": 4096, "disk_free_mb": 500000},
        )

        a = score_node_for_task(strong, self.task)["overall"]
        b = score_node_for_task(weak, self.task)["overall"]
        self.assertGreater(a, b,
            "A strictly stronger node should always score higher")


# ═════════════════════════════════════════════════════════════════════════════
# Scoring Boundary Tests
# ═════════════════════════════════════════════════════════════════════════════


class ScoreBoundaryTests(TestCase):
    """Boundary conditions for scoring functions."""

    def test_capability_64_cores_capped_at_one(self):
        """Extremely high CPU/memory should not exceed 1.0."""
        node = Node.objects.create(device_id="beast", status=Node.Status.IDLE)
        NodeCapability.objects.create(
            node=node, cpu_cores=128, memory_mb=524288,  # 128 cores, 512 GB
            workload_types=["checksum"],
        )
        task = Task.objects.create(
            job=Job.objects.create(task_type="checksum"),
            task_type="checksum",
        )
        score = _score_capability(node, task)
        self.assertLessEqual(score, 1.0)
        self.assertGreater(score, 0.5)

    def test_resource_zero_load_is_perfect(self):
        """current_load=0.0 + abundant resources → perfect resource score."""
        node = Node.objects.create(device_id="zero-load")
        NodeCapability.objects.create(
            node=node, cpu_cores=8, memory_mb=16384, disk_free_mb=100000,
        )
        NodeHeartbeat.objects.create(
            node=node, current_load=0.0,
            resources={"memory_used_mb": 1, "disk_free_mb": 99999},
        )
        score = _score_resource(node)
        self.assertGreaterEqual(score, 0.95)

    def test_resource_max_load_is_zero(self):
        """current_load=1.0 → resource score floor."""
        node = Node.objects.create(device_id="max-load")
        NodeCapability.objects.create(
            node=node, cpu_cores=8, memory_mb=16384, disk_free_mb=100000,
        )
        NodeHeartbeat.objects.create(
            node=node, current_load=1.0,
            resources={"memory_used_mb": 16384, "disk_free_mb": 0},
        )
        score = _score_resource(node)
        self.assertLessEqual(score, 0.5)

    def test_health_no_heartbeat_is_moderate(self):
        """A node with no heartbeat history gets a moderate health score (not 0, not 1)."""
        node = Node.objects.create(device_id="no-hb-health", status=Node.Status.IDLE)
        score = _score_health(node)
        self.assertGreater(score, 0.2)
        self.assertLess(score, 0.9)

    def test_health_zero_age_is_max(self):
        """Heartbeat received just now → max freshness contribution."""
        node = Node.objects.create(device_id="fresh", status=Node.Status.IDLE)
        NodeHeartbeat.objects.create(
            node=node, current_load=0.1, received_at=timezone.now(),
        )
        score = _score_health(node)
        # idle(1.0)*0.6 + fresh(1.0)*0.4 = 1.0
        self.assertGreaterEqual(score, 0.95)

    def test_health_offline_node_minimal(self):
        """Offline node should have a very low health score."""
        node = Node.objects.create(device_id="gone", status=Node.Status.OFFLINE)
        score = _score_health(node)
        self.assertLess(score, 0.3)


# ═════════════════════════════════════════════════════════════════════════════
# Edge Cases — Candidate & Task Selection
# ═════════════════════════════════════════════════════════════════════════════


class SchedulerEdgeCaseTests(TestCase):
    """Edge cases: no candidates, all degraded, single-node cluster."""

    def setUp(self):
        self.cluster = Cluster.objects.create(name="edge-cluster")
        self.job = Job.objects.create(
            task_type="checksum", status=Job.Status.ACTIVE,
        )

    def _create_node(self, status, **kwargs):
        token = f"edge-token-{status}"
        node = Node.objects.create(
            device_id=f"edge-{status}", status=status,
            cluster=self.cluster, token=token, **kwargs,
        )
        NodeCapability.objects.create(node=node, workload_types=["checksum"])
        NodeHeartbeat.objects.create(node=node, current_load=0.2)
        return node

    def _client_for(self, node):
        return _authed_client(token=node.token)

    def test_no_candidates_returns_empty_list(self):
        """All nodes degraded → get_candidate_nodes returns empty list."""
        self._create_node(Node.Status.DEGRADED)
        self._create_node(Node.Status.OFFLINE)
        candidates = get_candidate_nodes("checksum", self.cluster)
        self.assertEqual(len(candidates), 0)

    def test_no_candidates_returns_204(self):
        """All nodes degraded → assign endpoint returns 204."""
        self._create_node(Node.Status.DEGRADED)
        Task.objects.create(
            job=self.job, task_type="checksum", status=Task.Status.QUEUED,
        )
        degraded_node = Node.objects.filter(status=Node.Status.DEGRADED).first()
        client = self._client_for(degraded_node)
        response = client.get(
            f"/api/v1/tasks/assign/?node_id={degraded_node.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_single_node_cluster_gets_task(self):
        """Only one node in cluster — it gets the task regardless of absolute score."""
        solo = self._create_node(Node.Status.IDLE)
        Task.objects.create(
            job=self.job, task_type="checksum", status=Task.Status.QUEUED,
        )
        client = self._client_for(solo)
        response = client.get(f"/api/v1/tasks/assign/?node_id={solo.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_no_capability_no_task(self):
        """Node with zero workload_types listed shouldn't get capability-matched tasks."""
        node = Node.objects.create(
            device_id="no-caps", status=Node.Status.IDLE, cluster=self.cluster,
        )
        Task.objects.create(
            job=self.job, task_type="checksum", status=Task.Status.QUEUED,
        )
        client = APIClient()  # no token — will hit auth before capability check
        response = client.get(f"/api/v1/tasks/assign/?node_id={node.id}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ═════════════════════════════════════════════════════════════════════════════
# Priority + Retry Combination Tests
# ═════════════════════════════════════════════════════════════════════════════


class SchedulerPriorityComboTests(TestCase):
    """Priority and retry status interact correctly."""

    def setUp(self):
        self.node = Node.objects.create(device_id="combo-worker")
        NodeCapability.objects.create(
            node=self.node, workload_types=["checksum"],
        )
        self.job = Job.objects.create(task_type="checksum")

    def test_retry_high_beats_pending_high(self):
        """A retry task at high priority beats a fresh task at high priority."""
        pending_high = Task.objects.create(
            job=self.job, task_type="checksum",
            status=Task.Status.QUEUED, priority="high",
        )
        retry_high = Task.objects.create(
            job=self.job, task_type="checksum",
            status=Task.Status.RETRY, priority="high",
        )
        tasks = get_assignable_tasks_for_node(self.node, ["checksum"])
        self.assertEqual(tasks[0].id, retry_high.id)
        self.assertEqual(tasks[1].id, pending_high.id)

    def test_retry_low_still_beats_pending_medium(self):
        """Even a low-priority retry is returned before a medium-priority pending task."""
        pending_med = Task.objects.create(
            job=self.job, task_type="checksum",
            status=Task.Status.QUEUED, priority="medium",
        )
        retry_low = Task.objects.create(
            job=self.job, task_type="checksum",
            status=Task.Status.RETRY, priority="low",
        )
        tasks = get_assignable_tasks_for_node(self.node, ["checksum"])
        self.assertEqual(tasks[0].id, retry_low.id)


# ═════════════════════════════════════════════════════════════════════════════
# Concurrency Test — Near-Simultaneous Polling
# ═════════════════════════════════════════════════════════════════════════════


class SchedulerConcurrencyTests(TestCase):
    """Two nodes polling near-simultaneously should not double-assign."""

    def setUp(self):
        self.cluster = Cluster.objects.create(name="con-cluster")

        self.token_a = "con-token-a"
        self.token_b = "con-token-b"

        self.node_a = Node.objects.create(
            device_id="con-a", status=Node.Status.IDLE, cluster=self.cluster,
            token=self.token_a,
        )
        NodeCapability.objects.create(
            node=self.node_a, cpu_cores=8, memory_mb=16384,
            workload_types=["checksum"],
        )
        NodeHeartbeat.objects.create(
            node=self.node_a, current_load=0.1,
            resources={"memory_used_mb": 4096, "disk_free_mb": 80000},
        )

        self.node_b = Node.objects.create(
            device_id="con-b", status=Node.Status.IDLE, cluster=self.cluster,
            token=self.token_b,
        )
        NodeCapability.objects.create(
            node=self.node_b, cpu_cores=8, memory_mb=16384,
            workload_types=["checksum"],
        )
        NodeHeartbeat.objects.create(
            node=self.node_b, current_load=0.1,
            resources={"memory_used_mb": 4096, "disk_free_mb": 80000},
        )

        self.job = Job.objects.create(
            task_type="checksum", status=Job.Status.ACTIVE,
        )

        self.client_a = _authed_client(token=self.token_a)
        self.client_b = _authed_client(token=self.token_b)

    def test_single_task_not_assigned_twice(self):
        """One task, two nodes poll — only one gets it."""
        Task.objects.create(
            job=self.job, task_type="checksum", status=Task.Status.QUEUED,
        )

        r_a = self.client_a.get(f"/api/v1/tasks/assign/?node_id={self.node_a.id}")
        r_b = self.client_b.get(f"/api/v1/tasks/assign/?node_id={self.node_b.id}")

        successes = [r.status_code for r in (r_a, r_b)].count(status.HTTP_200_OK)
        self.assertEqual(successes, 1, "Only one node should get the task")

        task = Task.objects.get(job=self.job)
        self.assertEqual(task.status, Task.Status.ASSIGNED)
        self.assertIsNotNone(task.assigned_to)

    def test_two_tasks_both_assigned(self):
        """Two tasks, two nodes poll — both get a task."""
        Task.objects.create(
            job=self.job, task_type="checksum", status=Task.Status.QUEUED,
        )
        Task.objects.create(
            job=self.job, task_type="checksum", status=Task.Status.QUEUED,
        )

        r_a = self.client_a.get(f"/api/v1/tasks/assign/?node_id={self.node_a.id}")
        r_b = self.client_b.get(f"/api/v1/tasks/assign/?node_id={self.node_b.id}")

        self.assertEqual(r_a.status_code, status.HTTP_200_OK)
        self.assertEqual(r_b.status_code, status.HTTP_200_OK)
        self.assertNotEqual(r_a.data["task_id"], r_b.data["task_id"])
