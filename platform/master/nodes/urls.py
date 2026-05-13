from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ClusterViewSet, DiscoveryViewSet, NodeViewSet

router = DefaultRouter()
router.register(r"nodes", NodeViewSet, basename="node")
router.register(r"clusters", ClusterViewSet, basename="cluster")
router.register(r"discover", DiscoveryViewSet, basename="discover")

urlpatterns = [
    path("", include(router.urls)),
]
