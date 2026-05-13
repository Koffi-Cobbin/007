from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from orchestration.models import Task, TaskResult

from .models import Cluster, Node, NodeCapability, NodeHeartbeat


class _MembershipInline(admin.TabularInline):
    model = Node
    fields = ["hostname", "device_id", "status", "is_designated_master"]
    readonly_fields = ["hostname", "device_id", "status"]
    extra = 0
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = [
        "hostname", "device_id", "colored_status", "cluster_name",
        "is_designated_master", "ip_address", "heartbeat_freshness",
        "pending_tasks", "tasks_completed",
    ]
    list_filter = ["status", "platform", "cluster", "is_designated_master"]
    search_fields = ["hostname", "device_id", "ip_address"]
    readonly_fields = ["id", "created_at", "updated_at", "joined_at"]

    # ── Status badge ────────────────────────────────────────────────

    def colored_status(self, obj):
        colors = {
            "idle": "green",
            "active": "blue",
            "busy": "orange",
            "degraded": "red",
            "offline": "gray",
            "enrolling": "purple",
        }
        c = colors.get(obj.status, "gray")
        return format_html('<span style="color:{};font-weight:bold;">{}</span>', c, obj.status)
    colored_status.short_description = "Status"
    colored_status.admin_order_field = "status"

    # ── Heartbeat freshness with warning badge ──────────────────────

    def heartbeat_freshness(self, obj):
        if not obj.last_heartbeat:
            return format_html('<span style="color:gray;">never</span>')
        delta = timezone.now() - obj.last_heartbeat
        mins = int(delta.total_seconds() // 60)
        if mins < 1:
            return format_html('<span style="color:green;">just now</span>')
        if mins < 5:
            return f"{mins}m ago"
        return format_html(
            '<span style="color:red;font-weight:bold;">{}m ago ⚠</span>', mins,
        )
    heartbeat_freshness.short_description = "Heartbeat"

    # ── Task counts ─────────────────────────────────────────────────

    def pending_tasks(self, obj):
        return Task.objects.filter(
            assigned_to=obj, status__in=["pending", "queued", "assigned"],
        ).count()
    pending_tasks.short_description = "Pending"

    def tasks_completed(self, obj):
        return TaskResult.objects.filter(task__assigned_to=obj, status="completed").count()
    tasks_completed.short_description = "Done"

    # ── Cluster name ────────────────────────────────────────────────

    def cluster_name(self, obj):
        return obj.cluster.name if obj.cluster else "—"
    cluster_name.short_description = "Cluster"
    cluster_name.admin_order_field = "cluster__name"


@admin.register(NodeCapability)
class NodeCapabilityAdmin(admin.ModelAdmin):
    list_display = ["node", "cpu_cores", "memory_mb", "os_family", "reported_at"]
    list_filter = ["os_family"]
    readonly_fields = ["reported_at"]


@admin.register(NodeHeartbeat)
class NodeHeartbeatAdmin(admin.ModelAdmin):
    list_display = ["node", "status", "current_load", "current_task", "received_at"]
    list_filter = ["status"]
    readonly_fields = ["received_at"]


@admin.register(Cluster)
class ClusterAdmin(admin.ModelAdmin):
    list_display = ["name", "master_node", "discovery_method", "member_count", "created_at"]
    readonly_fields = ["id", "created_at", "updated_at"]
    inlines = [_MembershipInline]

    def member_count(self, obj):
        return obj.members.count()
    member_count.short_description = "Members"
