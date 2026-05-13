from rest_framework import serializers

from .models import Job, Task, TaskAssignment, TaskLog, TaskResult, WorkloadType


class TaskLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskLog
        fields = ["id", "task", "level", "message", "timestamp"]
        read_only_fields = ["id", "timestamp"]


class TaskResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskResult
        fields = [
            "id", "task", "status", "output", "error",
            "metrics", "logs", "reported_at",
        ]
        read_only_fields = ["id", "reported_at"]


class TaskAssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskAssignment
        fields = ["id", "task", "node", "assigned_at", "acknowledged_at", "completed_at"]
        read_only_fields = ["id", "assigned_at"]


class TaskSerializer(serializers.ModelSerializer):
    result = TaskResultSerializer(read_only=True)
    assignments = TaskAssignmentSerializer(many=True, read_only=True)
    logs = TaskLogSerializer(many=True, read_only=True)

    class Meta:
        model = Task
        fields = [
            "id", "job", "status", "task_type", "payload",
            "priority", "required_resources",
            "assigned_to", "timeout_seconds", "max_retries",
            "retry_count", "created_at", "updated_at", "completed_at",
            "result", "assignments", "logs",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "completed_at", "retry_count", "priority"]


class JobSerializer(serializers.ModelSerializer):
    tasks = TaskSerializer(many=True, read_only=True)

    class Meta:
        model = Job
        fields = [
            "id", "cluster", "status", "task_type", "input_payload",
            "priority",
            "created_at", "updated_at", "completed_at", "tasks",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "completed_at"]


class TaskAssignSerializer(serializers.Serializer):
    """Used when an agent polls for the next available task."""
    node_id = serializers.UUIDField()
    capabilities = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class WorkloadTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkloadType
        fields = [
            "id", "name", "description", "input_schema", "output_schema",
            "version", "is_active", "author", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
