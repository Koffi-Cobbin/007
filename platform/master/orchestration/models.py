import uuid

from django.db import models


class Priority(models.TextChoices):
    """Scheduling priority for jobs and tasks."""
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"


class Job(models.Model):
    """Top-level work unit submitted by a user or operator."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SPLITTING = "splitting", "Splitting"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cluster = models.ForeignKey(
        "nodes.Cluster", on_delete=models.SET_NULL, blank=True, null=True
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    task_type = models.CharField(max_length=64, blank=True, default="", db_index=True)
    input_payload = models.JSONField(default=dict, blank=True)
    priority = models.CharField(
        max_length=8,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        db_index=True,
        help_text="Scheduling priority: high, medium, low",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Job {self.id} — {self.status}"


class WorkloadType(models.Model):
    """Registry of known workload types with schema definitions.

    Each entry describes a type of work the system can perform, with
    JSON Schemas for input validation and output documentation.
    New types can be added without modifying core code — see Phase 7.
    """

    name = models.CharField(max_length=64, unique=True,
                            help_text="Unique identifier, e.g. 'checksum'")
    description = models.TextField(blank=True, default="")
    input_schema = models.JSONField(
        default=dict, blank=True,
        help_text="JSON Schema describing expected input_payload fields",
    )
    output_schema = models.JSONField(
        default=dict, blank=True,
        help_text="JSON Schema describing the expected output format",
    )
    version = models.CharField(max_length=16, default="1.0.0")
    is_active = models.BooleanField(default=True)
    author = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "workload type"

    def __str__(self):
        return f"{self.name} v{self.version}"


class Task(models.Model):
    """A single unit of work assigned to one node."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        QUEUED = "queued", "Queued"
        ASSIGNED = "assigned", "Assigned"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        RETRY = "retry", "Retry"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="tasks")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    task_type = models.CharField(max_length=64, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    required_resources = models.JSONField(
        default=dict, blank=True,
        help_text="Resource requirements: {min_cpu_cores, min_memory_mb, min_disk_mb}",
    )
    priority = models.CharField(
        max_length=8,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        db_index=True,
        help_text="Inherited from job; scheduling priority: high, medium, low",
    )
    assigned_to = models.ForeignKey(
        "nodes.Node", on_delete=models.SET_NULL, blank=True, null=True
    )
    timeout_seconds = models.IntegerField(default=300)
    max_retries = models.IntegerField(default=3)
    retry_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Task {self.id} — {self.status}"


class TaskAssignment(models.Model):
    """Records which node was assigned which task and when."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="assignments")
    node = models.ForeignKey("nodes.Node", on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-assigned_at"]

    def __str__(self):
        return f"{self.task.id} → {self.node.hostname or self.node.device_id}"


class TaskResult(models.Model):
    """Output or error produced by task execution."""

    class Status(models.TextChoices):
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    task = models.OneToOneField(
        Task, on_delete=models.CASCADE, related_name="result"
    )
    status = models.CharField(max_length=16, choices=Status.choices)
    output = models.JSONField(default=dict, blank=True)
    error = models.JSONField(blank=True, null=True)
    metrics = models.JSONField(default=dict, blank=True, help_text="started_at, completed_at, duration_seconds, peak_memory_mb")
    logs = models.TextField(blank=True, default="")
    reported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-reported_at"]

    def __str__(self):
        return f"Result for {self.task.id} — {self.status}"


class TaskLog(models.Model):
    """Execution log entries for a task."""

    class Level(models.TextChoices):
        INFO = "info", "Info"
        WARN = "warn", "Warn"
        ERROR = "error", "Error"

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="logs")
    level = models.CharField(max_length=8, choices=Level.choices, default=Level.INFO)
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["timestamp"]

    def __str__(self):
        return f"[{self.level}] {self.task.id} — {self.message[:60]}"
