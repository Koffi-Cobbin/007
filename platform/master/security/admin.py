from django.contrib import admin
from django.utils.html import format_html


from .models import AuditLog, EnrollmentKey, ProtocolVersion


@admin.register(EnrollmentKey)
class EnrollmentKeyAdmin(admin.ModelAdmin):
    list_display = ["key", "description", "active_badge", "used_by", "created_at", "expires_at"]
    list_filter = ["is_active"]
    readonly_fields = ["id", "created_at"]
    search_fields = ["key", "description"]

    def active_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="color:green;font-weight:bold;">Active</span>')
        return format_html('<span style="color:gray;">Used</span>')
    active_badge.short_description = "Status"
    active_badge.admin_order_field = "is_active"


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "colored_action", "actor_type", "actor_id", "resource_type", "resource_id"]
    list_filter = ["actor_type", "action", "resource_type"]
    readonly_fields = ["id", "timestamp"]
    search_fields = ["actor_id", "resource_id", "action"]
    date_hierarchy = "timestamp"

    def colored_action(self, obj):
        colors = {
            "node.register": "purple",
            "node.activate": "blue",
            "node.timeout": "red",
            "task.assign": "orange",
            "task.completed": "green",
            "task.failed": "red",
            "task.reassign": "darkorange",
            "job.create": "blue",
        }
        c = colors.get(obj.action, "gray")
        return format_html('<span style="color:{};font-weight:bold;">{}</span>', c, obj.action)
    colored_action.short_description = "Action"
    colored_action.admin_order_field = "action"


@admin.register(ProtocolVersion)
class ProtocolVersionAdmin(admin.ModelAdmin):
    list_display = ["version", "active_badge", "released_at", "deprecated_at"]
    list_filter = ["is_active"]
    readonly_fields = ["released_at"]

    def active_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="color:green;font-weight:bold;">Active</span>')
        return format_html('<span style="color:red;">Deprecated</span>')
    active_badge.short_description = "Status"
    active_badge.admin_order_field = "is_active"
