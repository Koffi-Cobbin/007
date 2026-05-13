from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AuditLogViewSet, EnrollmentKeyViewSet, ProtocolVersionViewSet

router = DefaultRouter()
router.register(r"enrollment-keys", EnrollmentKeyViewSet, basename="enrollment-key")
router.register(r"audit-logs", AuditLogViewSet, basename="audit-log")
router.register(r"protocol-versions", ProtocolVersionViewSet, basename="protocol-version")

urlpatterns = [
    path("", include(router.urls)),
]
