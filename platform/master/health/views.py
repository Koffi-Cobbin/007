"""
Health and readiness endpoints for load balancer checks and monitoring.

Phase 8 — Multi-Master Readiness
"""

import time

from django.conf import settings
from django.db import connections
from django.db.utils import OperationalError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

_start_time = time.time()


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """Lightweight liveness check — returns 200 if the process is alive.

    This is the endpoint a load balancer polls to decide if this master
    node should receive traffic.
    """
    return Response({
        "status": "alive",
        "uptime_seconds": int(time.time() - _start_time),
        "version": "1.0.0",
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def readiness(request):
    """Readiness check — returns 200 only if the backend can accept requests.

    Checks database connectivity. A load balancer uses this to decide
    if this master node is fully ready (e.g. after a failover).
    """
    db_conn = _check_database()
    if not db_conn["ok"]:
        return Response({
            "status": "not_ready",
            "database": db_conn,
        }, status=503)

    return Response({
        "status": "ready",
        "uptime_seconds": int(time.time() - _start_time),
        "version": "1.0.0",
        "database": db_conn,
    })


def _check_database() -> dict:
    """Return ``{"ok": True}`` or ``{"ok": False, "error": ...}``."""
    try:
        conn = connections["default"]
        conn.ensure_connection()
        return {"ok": True}
    except OperationalError as exc:
        return {"ok": False, "error": str(exc)}
