import uuid

from django.db import models


class EnrollmentKey(models.Model):
    """Pre-shared key for device enrollment."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=255, unique=True)
    description = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    used_by = models.ForeignKey(
        "nodes.Node", on_delete=models.SET_NULL, blank=True, null=True
    )

    class Meta:
        verbose_name_plural = "enrollment keys"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Key {self.key[:16]}... ({'active' if self.is_active else 'inactive'})"


class AuditLog(models.Model):
    """Immutable log of significant state changes in the system."""

    class ActorType(models.TextChoices):
        NODE = "node", "Node"
        USER = "user", "User"
        SYSTEM = "system", "System"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor_type = models.CharField(max_length=8, choices=ActorType.choices)
    actor_id = models.CharField(max_length=255, blank=True, default="")
    action = models.CharField(max_length=64, db_index=True)
    resource_type = models.CharField(max_length=64, blank=True, default="")
    resource_id = models.CharField(max_length=255, blank=True, default="")
    details = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"[{self.actor_type}] {self.action} — {self.resource_type} {self.resource_id}"


class ProtocolVersion(models.Model):
    """Tracks supported API protocol versions."""

    version = models.CharField(max_length=16, unique=True)
    is_active = models.BooleanField(default=True)
    released_at = models.DateTimeField(auto_now_add=True)
    deprecated_at = models.DateTimeField(blank=True, null=True)
    supported_until = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-released_at"]

    def __str__(self):
        status = "active" if self.is_active else "deprecated"
        return f"v{self.version} ({status})"
