from rest_framework import serializers

from .models import Cluster, Node, NodeCapability, NodeHeartbeat


class NodeJoinSerializer(serializers.Serializer):
    """Validates a node join request."""
    node_id = serializers.UUIDField()

    def validate_node_id(self, value):
        try:
            Node.objects.get(id=value)
        except Node.DoesNotExist:
            raise serializers.ValidationError("No node found with this ID.")
        return value


class ElectMasterSerializer(serializers.Serializer):
    """Validates a master election request."""
    node_id = serializers.UUIDField()

    def validate_node_id(self, value):
        try:
            node = Node.objects.get(id=value)
        except Node.DoesNotExist:
            raise serializers.ValidationError("No node found with this ID.")
        return value


class NodeCapabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = NodeCapability
        fields = [
            "cpu_cores", "cpu_architecture", "memory_mb", "disk_free_mb",
            "workload_types", "os_family", "os_distribution", "reported_at",
        ]
        read_only_fields = ["reported_at"]


class NodeHeartbeatSerializer(serializers.ModelSerializer):
    class Meta:
        model = NodeHeartbeat
        fields = [
            "id", "node", "status", "current_load", "current_task",
            "resources", "uptime_seconds", "received_at",
        ]
        read_only_fields = ["id", "node", "received_at"]


class NodeSerializer(serializers.ModelSerializer):
    capabilities = NodeCapabilitySerializer(many=True, read_only=True)
    last_heartbeat_data = serializers.SerializerMethodField()
    cluster_name = serializers.CharField(source="cluster.name", read_only=True, default="")

    class Meta:
        model = Node
        fields = [
            "id", "device_id", "hostname", "platform", "status",
            "ip_address", "agent_version", "last_heartbeat",
            "capabilities", "last_heartbeat_data",
            "cluster", "cluster_name", "joined_at", "is_designated_master",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "token", "joined_at"]

    def get_last_heartbeat_data(self, obj):
        latest = obj.heartbeats.first()
        if latest:
            return NodeHeartbeatSerializer(latest).data
        return None


class NodeRegistrationSerializer(serializers.Serializer):
    """Used for the initial POST /nodes/register endpoint."""
    device_id = serializers.CharField(max_length=255)
    hostname = serializers.CharField(max_length=255, required=False, default="")
    platform = serializers.CharField(max_length=32, required=False, default="")
    enrollment_key = serializers.CharField(max_length=255)
    capabilities = NodeCapabilitySerializer(required=False)
    agent_version = serializers.CharField(max_length=32, required=False, default="")

    def validate_device_id(self, value):
        if Node.objects.filter(device_id=value).exists():
            raise serializers.ValidationError("A node with this device_id is already enrolled.")
        return value


class ClusterDetailSerializer(serializers.ModelSerializer):
    """Cluster with member list."""
    member_count = serializers.SerializerMethodField()
    member_summary = serializers.SerializerMethodField()

    class Meta:
        model = Cluster
        fields = [
            "id", "name", "master_node", "discovery_method", "discovery_port",
            "member_count", "member_summary",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_member_count(self, obj):
        return obj.members.count()

    def get_member_summary(self, obj):
        return [
            {"id": str(n.id), "hostname": n.hostname, "status": n.status}
            for n in obj.members.all()[:50]
        ]


class ClusterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cluster
        fields = [
            "id", "name", "master_node", "discovery_method", "discovery_port",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
