from rest_framework import serializers

from .models import AuditLog, EnrollmentKey, ProtocolVersion


class EnrollmentKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = EnrollmentKey
        fields = ["id", "key", "description", "is_active", "created_at", "expires_at"]
        read_only_fields = ["id", "created_at"]


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            "id", "actor_type", "actor_id", "action",
            "resource_type", "resource_id", "details", "timestamp",
        ]
        read_only_fields = ["id", "timestamp"]


class ProtocolVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProtocolVersion
        fields = [
            "version", "is_active", "released_at",
            "deprecated_at", "supported_until",
        ]
        read_only_fields = ["released_at"]
