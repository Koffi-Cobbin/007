import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from django_q.tasks import async_task
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response

from nodes.models import Node
from security.auth import NodeTokenPermission, log_event

from .models import Job, Task, TaskAssignment, TaskResult, WorkloadType
from .scheduler import (
    find_best_node,
    get_assignable_tasks_for_node,
    get_candidate_nodes,
    score_node_for_task,
)
from .serializers import (
    JobSerializer,
    TaskAssignSerializer,
    TaskResultSerializer,
    TaskSerializer,
    WorkloadTypeSerializer,
)
from .tasks import _aggregate_job, _task_status_counts

logger = logging.getLogger(__name__)


class JobViewSet(viewsets.ModelViewSet):
    """
    API endpoint for job management.

    list     → GET    /api/v1/jobs/              (admin only)
    create   → POST   /api/v1/jobs/              (admin only)
    detail   → GET    /api/v1/jobs/{id}/         (admin only)
    progress → GET    /api/v1/jobs/{id}/progress/ (admin only)
    """
    queryset = Job.objects.prefetch_related("tasks__result", "tasks__assignments", "tasks__logs")
    serializer_class = JobSerializer

    def get_permissions(self):
        return [IsAdminUser()]

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def perform_create(self, serializer):
        """Auto-enqueue the split_job task when a job is created."""
        priority = self.request.data.get("priority", "medium")
        # Schema validation against registered WorkloadType (Phase 7)
        task_type = self.request.data.get("task_type", "")
        try:
            wt = WorkloadType.objects.get(name=task_type, is_active=True)
            errors = _validate_payload_against_schema(
                self.request.data.get("input_payload", {}),
                wt.input_schema,
            )
            if errors:
                from rest_framework.exceptions import ValidationError
                raise ValidationError({
                    "input_payload": errors,
                    "workload_type": task_type,
                    "hint": "Check the WorkloadType schema via GET /api/v1/workload-types/{name}/",
                })
        except WorkloadType.DoesNotExist:
            pass  # No schema registered — skip validation
        job = serializer.save(priority=priority)
        log_event(
            actor_type="user", actor_id=str(self.request.user.id) if self.request.user.is_authenticated else "anonymous",
            action="job.create",
            resource_type="job", resource_id=str(job.id),
            details={"task_type": job.task_type, "priority": job.priority},
        )
        async_task("orchestration.tasks.split_job", job_id=str(job.id))

    @action(detail=True, methods=["get"], url_path="progress")
    def progress(self, request, pk=None):
        """Return job progress: completion percentage and status counts."""
        job = self.get_object()
        counts = _task_status_counts(job)
        pct = (counts["completed"] / counts["total"] * 100) if counts["total"] > 0 else 0
        return Response({
            "job_id": str(job.id),
            "status": job.status,
            "total_tasks": counts["total"],
            "completed_tasks": counts["completed"],
            "failed_tasks": counts["failed"],
            "pending_tasks": counts["pending"],
            "progress_pct": round(pct, 1),
        })


class TaskViewSet(viewsets.ModelViewSet):
    """
    API endpoint for task management.

    list     → GET   /api/v1/tasks/                     (admin only)
    detail   → GET   /api/v1/tasks/{id}/                (admin only)
    assign   → GET   /api/v1/tasks/assign/?node_id=...  (requires node token)
    result   → POST  /api/v1/tasks/{id}/result/         (requires node token)
    """
    queryset = Task.objects.select_related("assigned_to", "result")
    serializer_class = TaskSerializer

    def get_permissions(self):
        if self.action in ("assign", "submit_result"):
            return [NodeTokenPermission()]
        return [IsAdminUser()]

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        node_filter = self.request.query_params.get("node_id")
        if node_filter:
            qs = qs.filter(assigned_to__id=node_filter)
        return qs

    @action(detail=False, methods=["get"], url_path="assign")
    def assign(self, request):
        ser = TaskAssignSerializer(data=request.query_params)
        ser.is_valid(raise_exception=True)

        node_id = ser.validated_data["node_id"]
        node = get_object_or_404(Node, id=node_id)

        # Determine which task types this node can handle
        supported_types = _get_node_supported_task_types(node)
        requested_types = ser.validated_data.get("capabilities") or []
        supported_types = supported_types or requested_types

        # Get tasks ordered by priority then age (best first)
        tasks = get_assignable_tasks_for_node(node, supported_types)

        if not tasks:
            return Response(status=status.HTTP_204_NO_CONTENT)

        assigned_task = None
        assigned_score = None
        cluster = node.cluster

        for task in tasks:
            if cluster is None:
                # No cluster — just check capability and assign
                assigned_task = task
                assigned_score = {"overall": 0.5, "breakdown": {}}
                break

            # Find candidate nodes for this task in the cluster
            candidates = get_candidate_nodes(task.task_type, cluster)
            if not candidates:
                continue

            # Score this node for this task
            node_score = score_node_for_task(node, task)

            # Find the best node overall
            best_node, best_score = find_best_node(task, candidates)

            # Accept if this node is the best OR within 30% of best
            if best_node is None:
                continue

            score_ratio = node_score["overall"] / max(best_score["overall"], 0.001)
            if best_node.id == node.id or score_ratio >= 0.7:
                assigned_task = task
                assigned_score = node_score
                break

            # If we are much worse (>30% gap), let a better node grab this task
            logger.info(
                "Skipping task %s for node %s — score %.2f vs best %.2f (node %s)",
                task.id, node.device_id, node_score["overall"],
                best_score["overall"], best_node.device_id,
            )

        if assigned_task is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        with transaction.atomic():
            assigned_task.status = Task.Status.ASSIGNED
            assigned_task.assigned_to = node
            assigned_task.save(update_fields=["status", "assigned_to", "updated_at"])

            TaskAssignment.objects.create(task=assigned_task, node=node)

        log_event(
            actor_type="node", actor_id=node.device_id,
            action="task.assign",
            resource_type="task", resource_id=str(assigned_task.id),
            details={
                "job_id": str(assigned_task.job.id),
                "task_type": assigned_task.task_type,
                "priority": assigned_task.priority,
                "score": assigned_score,
            },
        )

        return Response({
            "task_id": str(assigned_task.id),
            "job_id": str(assigned_task.job.id),
            "task_type": assigned_task.task_type,
            "payload": assigned_task.payload,
            "priority": assigned_task.priority,
            "deadline_seconds": assigned_task.timeout_seconds,
            "created_at": assigned_task.created_at.isoformat(),
            "scheduling_score": assigned_score,
        })

    @action(detail=True, methods=["post"], url_path="result")
    def submit_result(self, request, pk=None):
        task = self.get_object()

        status_value = request.data.get("status")
        if status_value not in ("completed", "failed", "cancelled"):
            return Response(
                {"error": {"code": "INVALID_STATUS", "message": "status must be 'completed', 'failed', or 'cancelled'"}},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        with transaction.atomic():
            TaskResult.objects.update_or_create(
                task=task,
                defaults={
                    "status": status_value,
                    "output": request.data.get("output", {}),
                    "error": request.data.get("error"),
                    "metrics": request.data.get("metrics", {}),
                    "logs": request.data.get("logs", ""),
                },
            )

            if status_value == "completed":
                task.status = Task.Status.COMPLETED
            elif status_value == "failed":
                if task.retry_count < task.max_retries:
                    task.status = Task.Status.RETRY
                    task.retry_count += 1
                else:
                    task.status = Task.Status.FAILED
            else:
                task.status = Task.Status.CANCELLED

            task.completed_at = TaskResult.objects.filter(task=task).latest("reported_at").reported_at
            task.save(update_fields=["status", "retry_count", "completed_at", "updated_at"])

        next_action = "retry" if task.status == Task.Status.RETRY else "none"

        log_event(
            actor_type="node",
            actor_id=task.assigned_to.device_id if task.assigned_to else "unknown",
            action=f"task.{status_value}",
            resource_type="task", resource_id=str(task.id),
            details={
                "job_id": str(task.job.id),
                "status": status_value,
                "retry_count": task.retry_count,
                "next_action": next_action,
            },
        )

        # Check if the parent job should be aggregated
        if task.status in (Task.Status.COMPLETED, Task.Status.FAILED, Task.Status.CANCELLED):
            async_task("orchestration.tasks._aggregate_job", job_id=str(task.job.id))

        return Response({
            "accepted": True,
            "next_action": next_action,
        })


# ═════════════════════════════════════════════════════════════════════
# Workload Registry  (Phase 7)
# ═════════════════════════════════════════════════════════════════════


class WorkloadTypeViewSet(viewsets.ModelViewSet):
    """
    API endpoint for the workload type registry.

    list     → GET    /api/v1/workload-types/         (admin / agents)
    create   → POST   /api/v1/workload-types/         (admin only)
    detail   → GET    /api/v1/workload-types/{name}/  (admin / agents)
    """
    queryset = WorkloadType.objects.filter(is_active=True)
    serializer_class = WorkloadTypeSerializer
    lookup_field = "name"

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAdminUser()]
        return [AllowAny()]  # readable by anyone (including agents)


# ═════════════════════════════════════════════════════════════════════
# Schema Validation  (Phase 7)
# ═════════════════════════════════════════════════════════════════════


def _validate_payload_against_schema(payload: dict, schema: dict) -> list:
    """Lightweight validation of *payload* against a JSON-Schema-like dict.

    Checks required fields and basic property types.  Returns a list of
    error messages (empty = valid).
    """
    errors = []
    if not schema:
        return errors

    for field_name in schema.get("required", []):
        if field_name not in payload:
            errors.append(f"Missing required field: '{field_name}'")

    for field_name, props in schema.get("properties", {}).items():
        if field_name not in payload:
            continue
        value = payload[field_name]
        expected = props.get("type")
        if expected == "array" and not isinstance(value, list):
            errors.append(f"Field '{field_name}' must be an array")
        elif expected == "string" and not isinstance(value, str):
            errors.append(f"Field '{field_name}' must be a string")
        elif expected == "object" and not isinstance(value, dict):
            errors.append(f"Field '{field_name}' must be an object")
        elif expected == "integer" and not isinstance(value, int):
            errors.append(f"Field '{field_name}' must be an integer")
        elif expected == "number" and not isinstance(value, (int, float)):
            errors.append(f"Field '{field_name}' must be a number")
    return errors


# ── Scheduling helpers ──────────────────────────────────────────────

def _get_node_supported_task_types(node) -> list[str]:
    """Return list of task types a node supports based on its capabilities."""
    try:
        latest = node.capabilities.order_by("-reported_at").first()
        if latest and latest.workload_types:
            return latest.workload_types
    except Exception:
        pass
    return []
