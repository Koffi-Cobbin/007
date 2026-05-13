import uuid

from django.db import models


class Node(models.Model):
    """A device (laptop, desktop) participating in the cluster."""

    class Status(models.TextChoices):
        OFFLINE = "offline", "Offline"
        ENROLLING = "enrolling", "Enrolling"
        ACTIVE = "active", "Active"
        IDLE = "idle", "Idle"
        BUSY = "busy", "Busy"
        DEGRADED = "degraded", "Degraded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_id = models.CharField(max_length=255, unique=True, help_text="Unique persistent device identifier")
    hostname = models.CharField(max_length=255, blank=True, default="")
    platform = models.CharField(max_length=32, blank=True, default="", help_text="e.g. windows, linux")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OFFLINE,
        db_index=True,
    )
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    token = models.CharField(max_length=255, blank=True, default="", help_text="Bearer token for API auth")
    agent_version = models.CharField(max_length=32, blank=True, default="")
    cluster = models.ForeignKey(
        "Cluster", on_delete=models.SET_NULL, blank=True, null=True, related_name="members"
    )
    joined_at = models.DateTimeField(blank=True, null=True)
    is_designated_master = models.BooleanField(default=False)
    last_heartbeat = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.hostname or self.device_id} ({self.status})"


class NodeCapability(models.Model):
    """Declared capabilities of a node (reported during enrollment / heartbeat)."""

    node = models.ForeignKey(
        Node, on_delete=models.CASCADE, related_name="capabilities"
    )
    cpu_cores = models.IntegerField(default=0)
    cpu_architecture = models.CharField(max_length=32, blank=True, default="")
    memory_mb = models.IntegerField(default=0, help_text="Total RAM in MB")
    disk_free_mb = models.IntegerField(default=0, help_text="Free disk in MB at time of report")
    workload_types = models.JSONField(default=list, blank=True, help_text="List of supported workload type identifiers")
    os_family = models.CharField(max_length=32, blank=True, default="")
    os_distribution = models.CharField(max_length=128, blank=True, default="")
    reported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "node capabilities"
        ordering = ["-reported_at"]

    def __str__(self):
        return f"{self.node.hostname or self.node.device_id} — {self.cpu_cores} cores / {self.memory_mb} MB"


class NodeHeartbeat(models.Model):
    """Periodic status report from a node."""

    node = models.ForeignKey(
        Node, on_delete=models.CASCADE, related_name="heartbeats"
    )
    status = models.CharField(max_length=16, blank=True, default="")
    current_load = models.FloatField(default=0.0, help_text="CPU load 0.0–1.0")
    current_task = models.UUIDField(blank=True, null=True, help_text="Task ID if busy")
    resources = models.JSONField(default=dict, blank=True, help_text="cpu_percent, memory_used_mb, disk_free_mb")
    uptime_seconds = models.BigIntegerField(default=0)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.node.hostname or self.node.device_id} — {self.status} @ {self.received_at}"


class Cluster(models.Model):
    """Cluster membership and configuration."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    master_node = models.ForeignKey(
        Node, on_delete=models.SET_NULL, blank=True, null=True, related_name="master_of"
    )
    discovery_method = models.CharField(max_length=64, blank=True, default="manual")
    discovery_port = models.IntegerField(default=42069, help_text="UDP port for LAN discovery beacons")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} (master: {self.master_node})"
