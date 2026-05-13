"""
Authentication and authorization for node-to-backend communication.

Provides:
  - NodeTokenAuthentication  — DRF auth backend (Bearer token → Node lookup)
  - NodeTokenPermission      — Permission class for node-authenticated endpoints
  - log_event                — Helper to write structured AuditLog entries
"""

import logging

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import BasePermission

from nodes.models import Node

from .models import AuditLog

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# Authentication
# ═════════════════════════════════════════════════════════════════════════════


class NodeTokenAuthentication(BaseAuthentication):
    """DRF authentication backend that validates ``Authorization: Bearer <token>``
    headers against the ``Node.token`` field.

    Returns ``(node_instance, token_string)`` on success, ``None`` if no
    token is present (delegates to other backends), or raises
    ``AuthenticationFailed`` on invalid tokens.
    """

    keyword = "Bearer"

    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth or auth[0].lower() != self.keyword.lower().encode():
            return None  # No auth header — let other backends try

        if len(auth) == 1:
            raise AuthenticationFailed("Invalid Authorization header — no token provided")
        if len(auth) > 2:
            raise AuthenticationFailed("Invalid Authorization header — extra content")

        token = auth[1].decode()
        try:
            node = Node.objects.get(token=token)
        except Node.DoesNotExist:
            raise AuthenticationFailed("Invalid or expired token")

        # Refuse tokens for nodes in a terminal bad state
        if node.status == Node.Status.OFFLINE:
            raise AuthenticationFailed("Node is offline — re-register required")

        return (node, token)

    def authenticate_header(self, request):
        return "Bearer"


# ═════════════════════════════════════════════════════════════════════════════
# Permissions
# ═════════════════════════════════════════════════════════════════════════════


class NodeTokenPermission(BasePermission):
    """Allows access only to requests authenticated with a valid node Bearer
    token (i.e. ``request.auth is not None``)."""

    def has_permission(self, request, view):
        if request.auth is None:
            raise PermissionDenied("Authentication required — send Authorization: Bearer <token>")
        return True


# ═════════════════════════════════════════════════════════════════════════════
# Audit logging
# ═════════════════════════════════════════════════════════════════════════════


def log_event(
    actor_type: str,
    actor_id: str,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    details: dict | None = None,
):
    """Write a structured entry to the ``AuditLog`` table.

    Parameters mirror the ``AuditLog`` model fields. This is the *only*
    place that creates ``AuditLog`` rows, ensuring consistent formatting.

    Common ``action`` values:

    ====================  ===========================
    Action                When
    ====================  ===========================
    ``node.register``     Node successfully enrolled
    ``node.activate``     Node transitioned to active
    ``node.timeout``      Stale node marked offline
    ``node.heartbeat``    Heartbeat received
    ``task.assign``       Task assigned to a node
    ``task.complete``     Task completed successfully
    ``task.fail``         Task failed
    ``task.reassign``     Task reassigned after node timeout
    ``job.create``        Job created
    ====================  ===========================
    """
    AuditLog.objects.create(
        actor_type=actor_type,
        actor_id=str(actor_id)[:255],
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id)[:255],
        details=details or {},
    )
    logger.debug("Audit: [%s] %s — %s %s", actor_type, action, resource_type, resource_id)
