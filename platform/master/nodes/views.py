from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response

from security.auth import NodeTokenPermission, log_event
from security.models import EnrollmentKey

from orchestration.models import Task, TaskResult

from .models import Cluster, Node, NodeCapability, NodeHeartbeat
from .serializers import (
    ClusterDetailSerializer,
    ClusterSerializer,
    ElectMasterSerializer,
    NodeCapabilitySerializer,
    NodeHeartbeatSerializer,
    NodeJoinSerializer,
    NodeRegistrationSerializer,
    NodeSerializer,
)


class NodeViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing cluster nodes.

    register        → POST   /api/v1/nodes/register/          (no auth — uses enrollment key)
    activate        → PUT    /api/v1/nodes/{id}/activate/     (requires node token)
    heartbeat       → POST   /api/v1/nodes/{id}/heartbeat/    (requires node token)
    capabilities    → POST   /api/v1/nodes/{id}/capabilities/ (requires node token)
    health          → GET    /api/v1/nodes/{id}/health/       (requires node token)
    list            → GET    /api/v1/nodes/                   (admin only)
    detail          → GET    /api/v1/nodes/{id}               (admin only)
    """
    queryset = Node.objects.prefetch_related("capabilities", "heartbeats")
    serializer_class = NodeSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def get_permissions(self):
        """Assign permissions per action."""
        if self.action == "register":
            return [AllowAny()]
        if self.action in ("list", "retrieve", "create", "update", "partial_update", "destroy"):
            return [IsAdminUser()]
        return [NodeTokenPermission()]

    @action(detail=False, methods=["post"], url_path="register")
    def register(self, request):
        ser = NodeRegistrationSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        # Validate enrollment key
        key_value = ser.validated_data["enrollment_key"]
        try:
            ek = EnrollmentKey.objects.get(key=key_value, is_active=True)
        except EnrollmentKey.DoesNotExist:
            return Response(
                {"error": {"code": "INVALID_ENROLLMENT_KEY", "message": "The provided enrollment key is invalid or inactive."}},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Create the node
        node = Node.objects.create(
            device_id=ser.validated_data["device_id"],
            hostname=ser.validated_data.get("hostname", ""),
            platform=ser.validated_data.get("platform", ""),
            status=Node.Status.ENROLLING,
            agent_version=ser.validated_data.get("agent_version", ""),
        )

        # Record capability if provided
        caps_data = ser.validated_data.get("capabilities")
        if caps_data:
            NodeCapability.objects.create(node=node, **caps_data)

        # Mark enrollment key as used
        ek.is_active = False
        ek.used_by = node
        ek.save()

        log_event(
            actor_type="node", actor_id=node.device_id,
            action="node.register",
            resource_type="node", resource_id=str(node.id),
            details={"device_id": node.device_id, "platform": node.platform},
        )

        return Response(
            {
                "node_id": str(node.id),
                "status": node.status,
                "token": node.token or "",
                "heartbeat_interval_seconds": 30,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["put"], url_path="activate")
    def activate(self, request, pk=None):
        node = self.get_object()
        node.status = Node.Status.ACTIVE
        node.save(update_fields=["status"])

        log_event(
            actor_type="node", actor_id=node.device_id,
            action="node.activate",
            resource_type="node", resource_id=str(node.id),
        )

        return Response({"node_id": str(node.id), "status": node.status})

    @action(detail=True, methods=["post"], url_path="heartbeat")
    def heartbeat(self, request, pk=None):
        node = self.get_object()
        ser = NodeHeartbeatSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        NodeHeartbeat.objects.create(node=node, **ser.validated_data)
        node.last_heartbeat = NodeHeartbeat.objects.filter(node=node).latest("received_at").received_at
        if ser.validated_data.get("status"):
            node.status = ser.validated_data["status"]
        node.save(update_fields=["last_heartbeat", "status"])

        pending_count = node.task_set.filter(
            status__in=["pending", "queued", "assigned"]
        ).count()

        return Response({
            "accepted": True,
            "next_heartbeat_in": 30,
            "pending_tasks": pending_count,
        })

    @action(detail=True, methods=["post"], url_path="capabilities")
    def report_capabilities(self, request, pk=None):
        node = self.get_object()
        ser = NodeCapabilitySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        cap = NodeCapability.objects.create(node=node, **ser.validated_data)
        return Response(NodeCapabilitySerializer(cap).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="health")
    def health(self, request, pk=None):
        """Return a summary of node health for monitoring / load balancers."""
        node = self.get_object()
        latest_hb = node.heartbeats.order_by("-received_at").first()

        pending = Task.objects.filter(
            assigned_to=node, status__in=["pending", "queued", "assigned"],
        ).count()
        completed = TaskResult.objects.filter(
            task__assigned_to=node, status="completed",
        ).count()
        failed = TaskResult.objects.filter(
            task__assigned_to=node, status="failed",
        ).count()

        return Response({
            "node_id": str(node.id),
            "device_id": node.device_id,
            "hostname": node.hostname,
            "status": node.status,
            "is_master": node.is_designated_master,
            "last_heartbeat": latest_hb.received_at.isoformat() if latest_hb else None,
            "uptime_seconds": latest_hb.uptime_seconds if latest_hb else 0,
            "current_load": latest_hb.current_load if latest_hb else 0.0,
            "resources": latest_hb.resources if latest_hb else {},
            "pending_tasks": pending,
            "tasks_completed": completed,
            "tasks_failed": failed,
            "cluster_id": str(node.cluster.id) if node.cluster else None,
            "cluster_name": node.cluster.name if node.cluster else None,
        })


class ClusterViewSet(viewsets.ModelViewSet):
    """
    API endpoint for cluster management.

    list        → GET    /api/v1/clusters/
    create      → POST   /api/v1/clusters/
    detail      → GET    /api/v1/clusters/{id}/
    members     → GET    /api/v1/clusters/{id}/members/
    join        → POST   /api/v1/clusters/{id}/join/
    leave       → POST   /api/v1/clusters/{id}/leave/
    elect-master → POST  /api/v1/clusters/{id}/elect-master/
    """
    queryset = Cluster.objects.all()
    serializer_class = ClusterSerializer

    def retrieve(self, request, *args, **kwargs):
        self.serializer_class = ClusterDetailSerializer
        return super().retrieve(request, *args, **kwargs)

    @action(detail=True, methods=["get"], url_path="members")
    def members(self, request, pk=None):
        """List all active members of the cluster."""
        cluster = self.get_object()
        nodes = cluster.members.all().order_by("-joined_at")
        return Response([
            {
                "id": str(n.id),
                "hostname": n.hostname,
                "device_id": n.device_id,
                "status": n.status,
                "is_master": cluster.master_node_id == n.id,
                "is_designated_master": n.is_designated_master,
                "ip_address": n.ip_address,
                "joined_at": n.joined_at.isoformat() if n.joined_at else None,
                "last_heartbeat": n.last_heartbeat.isoformat() if n.last_heartbeat else None,
            }
            for n in nodes
        ])

    @action(detail=True, methods=["post"], url_path="join")
    def join(self, request, pk=None):
        """Add a node to this cluster."""
        cluster = self.get_object()
        ser = NodeJoinSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        node = Node.objects.get(id=ser.validated_data["node_id"])
        node.cluster = cluster
        node.joined_at = timezone.now()
        node.save(update_fields=["cluster", "joined_at", "updated_at"])

        return Response({
            "cluster_id": str(cluster.id),
            "cluster_name": cluster.name,
            "node_id": str(node.id),
            "status": "joined",
        })

    @action(detail=True, methods=["post"], url_path="leave")
    def leave(self, request, pk=None):
        """Remove a node from this cluster."""
        cluster = self.get_object()
        ser = NodeJoinSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        node = Node.objects.get(id=ser.validated_data["node_id"])
        was_master = cluster.master_node_id == node.id

        node.cluster = None
        node.joined_at = None
        node.is_designated_master = False
        node.save(update_fields=["cluster", "joined_at", "is_designated_master", "updated_at"])

        if was_master:
            cluster.master_node = None
            cluster.save(update_fields=["master_node", "updated_at"])

        return Response({
            "node_id": str(node.id),
            "cluster_id": str(cluster.id),
            "status": "left",
        })

    @action(detail=True, methods=["post"], url_path="elect-master")
    def elect_master(self, request, pk=None):
        """Designate a node as the cluster master."""
        cluster = self.get_object()
        ser = ElectMasterSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        node = Node.objects.get(id=ser.validated_data["node_id"])

        if node.cluster_id != cluster.id:
            return Response(
                {"error": {"code": "NODE_NOT_IN_CLUSTER", "message": "Node is not a member of this cluster."}},
                status=status.HTTP_409_CONFLICT,
            )

        # Clear previous master designation
        Cluster.objects.filter(master_node=node).exclude(id=cluster.id).update(master_node=None)
        cluster.master_node = node
        cluster.save(update_fields=["master_node", "updated_at"])

        node.is_designated_master = True
        node.save(update_fields=["is_designated_master", "updated_at"])

        return Response({
            "cluster_id": str(cluster.id),
            "cluster_name": cluster.name,
            "master_node_id": str(node.id),
            "master_hostname": node.hostname,
            "status": "elected",
        })


class DiscoveryViewSet(viewsets.ViewSet):
    """Beacon endpoint for LAN discovery — returns master info."""

    def list(self, request):
        """GET /api/v1/discover/ — returns this node's identity for UDP discovery responders."""
        clusters = Cluster.objects.filter(master_node__isnull=False).select_related("master_node")
        data = []
        for cluster in clusters:
            master = cluster.master_node
            data.append({
                "cluster_id": str(cluster.id),
                "cluster_name": cluster.name,
                "master_node_id": str(master.id),
                "master_hostname": master.hostname,
                "master_url": f"http://{master.ip_address or 'localhost'}:8000",
                "discovery_port": cluster.discovery_port,
                "api_version": "1.0",
            })
        return Response({"servers": data})
