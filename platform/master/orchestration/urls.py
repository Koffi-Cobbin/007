from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import JobViewSet, TaskViewSet, WorkloadTypeViewSet

router = DefaultRouter()
router.register(r"jobs", JobViewSet, basename="job")
router.register(r"tasks", TaskViewSet, basename="task")
router.register(r"workload-types", WorkloadTypeViewSet, basename="workload-type")

urlpatterns = [
    path("", include(router.urls)),
]
