"""
Shared test utilities for Phase 6 auth tests.

Provides helpers to create authenticated API clients for both node-token
auth and admin-session auth.
"""

from rest_framework.test import APIClient

from django.contrib.auth.models import User

from nodes.models import Node, NodeCapability, NodeHeartbeat
from security.models import EnrollmentKey


def create_authed_node(device_id="authed-node", status=Node.Status.ACTIVE,
                       token="test-token-abc", cluster=None,
                       capabilities=None, heartbeat_data=None) -> Node:
    """Create a Node and assign it a token for authenticated requests.

    Returns the Node instance.
    """
    node = Node.objects.create(
        device_id=device_id,
        hostname=f"{device_id}.local",
        status=status,
        token=token,
        cluster=cluster,
    )
    if capabilities:
        NodeCapability.objects.create(node=node, **capabilities)
    if heartbeat_data:
        NodeHeartbeat.objects.create(node=node, **heartbeat_data)
    return node


def authed_client(token="test-token-abc") -> APIClient:
    """Return an APIClient pre-configured with a Bearer token."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def admin_client() -> APIClient:
    """Return an APIClient authenticated as a Django superuser."""
    User.objects.create_superuser("admin", "admin@test.com", "password")
    client = APIClient()
    client.login(username="admin", password="password")
    return client


def enrollment_key_client(key="test-key") -> APIClient:
    """Create an active enrollment key and return an unauthenticated client.

    The client is deliberately *not* authed — registration uses enrollment
    keys, not bearer tokens.
    """
    EnrollmentKey.objects.create(key=key, is_active=True)
    return APIClient()
