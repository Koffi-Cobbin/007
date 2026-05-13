"""
django-q2 async tasks for job splitting and orchestration.

Registered as async tasks callable via:
    async_task("orchestration.tasks.split_job", job_id=...)
"""

import logging

logger = logging.getLogger(__name__)


def split_job(job_id: str):
    """Split a Job into sub-tasks based on its task_type and input_payload.

    Called asynchronously via django-q2 when a job is created.
    Handles the 6 v1 workload types:

    1. file_processing    → one task per file
    2. image_processing   → one task per file
    3. checksum           → one task per file (or per algorithm)
    4. data_transform     → one task per partition
    5. python_execution   → one task per chunk (args range)
    6. numerical          → one task per chunk
    """
    from django.db import transaction

    from .models import Job, Task

    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        logger.error("split_job: job %s not found", job_id)
        return

    if job.status != Job.Status.PENDING:
        logger.warning("split_job: job %s is %s, not splitting", job_id, job.status)
        return

    job.status = Job.Status.SPLITTING
    job.save(update_fields=["status", "updated_at"])

    payload = job.input_payload or {}
    task_type = job.task_type
    job_priority = job.priority  # inherited by all sub-tasks
    tasks_data = _compute_task_chunks(task_type, payload)

    if not tasks_data:
        # Fallback: create a single task with the full payload
        tasks_data = [{"payload": payload}]

    with transaction.atomic():
        for chunk in tasks_data:
            Task.objects.create(
                job=job,
                task_type=task_type,
                status=Task.Status.QUEUED,
                priority=job_priority,
                payload=chunk.get("payload", payload),
                timeout_seconds=chunk.get("timeout", 300),
            )

    job.status = Job.Status.ACTIVE
    job.save(update_fields=["status", "updated_at"])
    logger.info(
        "split_job: job %s → %s sub-tasks (type=%s)",
        job_id, len(tasks_data), task_type,
    )


def _compute_task_chunks(task_type: str, payload: dict) -> list[dict]:
    """Compute the list of sub-task payloads for a given job type."""

    # Types that don't rely on input files
    if task_type == "python_execution":
        chunks = payload.get("chunks", [])
        if chunks:
            return [{"payload": {**payload, "chunk": c}} for c in chunks]
        return [{"payload": payload}]

    if task_type == "numerical":
        total_chunks = payload.get("total_chunks", 1)
        return [
            {"payload": {**payload, "chunk_index": i, "total_chunks": total_chunks}}
            for i in range(total_chunks)
        ]

    # Remaining types require files
    files = payload.get("files", [])

    if not files:
        return []

    if task_type in ("file_processing", "image_processing", "checksum"):
        # One task per file
        params = {k: v for k, v in payload.items() if k != "files"}
        return [{"payload": {"files": [f], **params}} for f in files]

    if task_type == "data_transform":
        partitions = payload.get("partitions", [])
        if partitions:
            return [{"payload": {**payload, "partition": p}} for p in partitions]
        # Fallback: one task per file
        params = {k: v for k, v in payload.items() if k != "files"}
        return [{"payload": {"files": [f], **params}} for f in files]

    # Default: one task per file
    params = {k: v for k, v in payload.items() if k != "files"}
    return [{"payload": {"files": [f], **params}} for f in files]


def _aggregate_job(job_id: str):
    """Check if all tasks in a job are done and update job status.

    Called automatically after a task result is submitted.
    """
    from .models import Job, Task

    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        return

    task_counts = _task_status_counts(job)

    total = task_counts["total"]
    completed = task_counts["completed"]
    failed = task_counts["failed"]

    if completed == total:
        job.status = Job.Status.COMPLETED
        from django.utils import timezone
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "completed_at", "updated_at"])
        logger.info("aggregate_job: job %s → COMPLETED (%s/%s tasks)", job_id, completed, total)

    elif failed == total:
        job.status = Job.Status.FAILED
        from django.utils import timezone
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "completed_at", "updated_at"])
        logger.info("aggregate_job: job %s → FAILED (%s/%s tasks)", job_id, failed, total)


def _task_status_counts(job) -> dict:
    """Return counts of tasks grouped by status."""
    from django.db.models import Count

    from .models import Task

    counts = (
        Task.objects.filter(job=job)
        .values("status")
        .annotate(count=Count("id"))
    )
    result = {"total": 0, "completed": 0, "failed": 0, "pending": 0}
    for entry in counts:
        status = entry["status"]
        count = entry["count"]
        result["total"] += count
        if status in ("completed",):
            result["completed"] += count
        elif status in ("failed", "cancelled"):
            result["failed"] += count
        else:
            result["pending"] += count
    return result
