from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser

from .models import AuditLog, EnrollmentKey, ProtocolVersion
from .serializers import (
    AuditLogSerializer,
    EnrollmentKeySerializer,
    ProtocolVersionSerializer,
)


class EnrollmentKeyViewSet(viewsets.ModelViewSet):
    queryset = EnrollmentKey.objects.all()
    serializer_class = EnrollmentKeySerializer

    def get_permissions(self):
        return [IsAdminUser()]


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer

    def get_permissions(self):
        return [IsAdminUser()]

    def get_queryset(self):
        qs = super().get_queryset()
        action_filter = self.request.query_params.get("action")
        if action_filter:
            qs = qs.filter(action=action_filter)
        return qs


class ProtocolVersionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProtocolVersion.objects.all()
    serializer_class = ProtocolVersionSerializer

    def get_permissions(self):
        return [IsAdminUser()]
