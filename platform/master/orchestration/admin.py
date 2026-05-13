from django.contrib import admin
from django.utils.html import format_html

from .models import Job, Task, TaskAssignment, TaskLog, TaskResult, WorkloadType


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = [
        "short_id", "status", "task_type", "priority_colored",
        "task_count", "cluster", "created_at", "completed_at",
    ]
    list_filter = ["status", "task_type", "priority"]
    readonly_fields = ["id", "created_at", "updated_at", "completed_at"]
    search_fields = ["id"]

    def short_id(self, obj):
        return str(obj.id)[:8] + "…"
    short_id.short_description = "ID"

    def priority_colored(self, obj):
        colors = {"high": "red", "medium": "orange", "low": "green"}
        c = colors.get(obj.priority, "gray")
        return format_html('<span style="color:{};font-weight:bold;">{}</span>', c, obj.priority)
    priority_colored.short_description = "Priority"
    priority_colored.admin_order_field = "priority"

    def task_count(self, obj):
        return obj.tasks.count()
    task_count.short_description = "Tasks"


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = [
        "short_id", "job_link", "colored_status", "task_type",
        "priority_colored", "assigned_to", "retry_count", "created_at",
    ]
    list_filter = ["status", "task_type", "priority"]
    readonly_fields = ["id", "created_at", "updated_at", "completed_at"]
    search_fields = ["id", "job__id"]

    def short_id(self, obj):
        return str(obj.id)[:8] + "…"
    short_id.short_description = "ID"

    def job_link(self, obj):
        from django.urls import reverse
        url = reverse("admin:orchestration_job_change", args=[obj.job_id])
        return format_html('<a href="{}">{}</a>', url, str(obj.job.id)[:8] + "…")
    job_link.short_description = "Job"
    job_link.admin_order_field = "job"

    def colored_status(self, obj):
        colors = {
            "completed": "green", "assigned": "blue", "running": "orange",
            "retry": "red", "failed": "darkred", "pending": "gray", "queued": "gray",
        }
        c = colors.get(obj.status, "gray")
        return format_html('<span style="color:{};font-weight:bold;">{}</span>', c, obj.status)
    colored_status.short_description = "Status"
    colored_status.admin_order_field = "status"

    def priority_colored(self, obj):
        colors = {"high": "red", "medium": "orange", "low": "green"}
        c = colors.get(obj.priority, "gray")
        return format_html('<span style="color:{};font-weight:bold;">{}</span>', c, obj.priority)
    priority_colored.short_description = "Priority"
    priority_colored.admin_order_field = "priority"


@admin.register(TaskAssignment)
class TaskAssignmentAdmin(admin.ModelAdmin):
    list_display = ["task", "node", "assigned_at", "acknowledged_at", "completed_at"]
    readonly_fields = ["assigned_at"]


@admin.register(TaskResult)
class TaskResultAdmin(admin.ModelAdmin):
    list_display = ["task", "colored_status", "duration", "reported_at"]
    list_filter = ["status"]
    readonly_fields = ["reported_at"]

    def colored_status(self, obj):
        c = "green" if obj.status == "completed" else "red"
        return format_html('<span style="color:{};font-weight:bold;">{}</span>', c, obj.status)
    colored_status.short_description = "Status"
    colored_status.admin_order_field = "status"

    def duration(self, obj):
        return obj.metrics.get("duration_seconds", "—") if obj.metrics else "—"
    duration.short_description = "Duration (s)"


@admin.register(TaskLog)
class TaskLogAdmin(admin.ModelAdmin):
    list_display = ["task", "colored_level", "message", "timestamp"]
    list_filter = ["level"]
    readonly_fields = ["timestamp"]

    def colored_level(self, obj):
        colors = {"info": "blue", "warn": "orange", "error": "red"}
        c = colors.get(obj.level, "gray")
        return format_html('<span style="color:{};font-weight:bold;">{}</span>', c, obj.level.upper())
    colored_level.short_description = "Level"
    colored_level.admin_order_field = "level"


@admin.register(WorkloadType)
class WorkloadTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "version", "is_active_badge", "author", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "description", "author"]
    readonly_fields = ["created_at", "updated_at"]

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="color:green;font-weight:bold;">Active</span>')
        return format_html('<span style="color:gray;">Inactive</span>')
    is_active_badge.short_description = "Active"
    is_active_badge.admin_order_field = "is_active"
