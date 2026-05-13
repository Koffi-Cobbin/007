from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("health.urls")),       # /health/ and /ready/
    path("api/v1/", include("nodes.urls")),
    path("api/v1/", include("orchestration.urls")),
    path("api/v1/", include("security.urls")),
]
