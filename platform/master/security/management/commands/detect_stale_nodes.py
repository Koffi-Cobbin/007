"""
Management command to detect nodes with stale heartbeats and recover their
assigned tasks.

Usage::

    python manage.py detect_stale_nodes
    python manage.py detect_stale_nodes --max-age 600 --dry-run

Designed to be run periodically via cron / Task Scheduler (e.g. every 5
minutes).
"""

import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from nodes.models import Node, NodeHeartbeat
from orchestration.models import Task
from security.auth import log_event

logger = logging.getLogger(__name__)

STALE_AFTER_SECONDS_DEFAULT = 300  # 5 minutes


class Command(BaseCommand):
    help = "Detect nodes with stale heartbeats and reassign their tasks"

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-age",
            type=int,
            default=STALE_AFTER_SECONDS_DEFAULT,
            help=f"Seconds since last heartbeat before a node is considered stale "
                 f"(default: {STALE_AFTER_SECONDS_DEFAULT})",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Scan and report without making changes",
        )

    def handle(self, *args, **options):
        max_age = options["max_age"]
        dry_run = options["dry_run"]

        cutoff = timezone.now() - timedelta(seconds=max_age)

        # Nodes that are supposed to be alive but haven't checked in
        stale_nodes = Node.objects.filter(
            last_heartbeat__lt=cutoff,
            status__in=[Node.Status.ACTIVE, Node.Status.IDLE, Node.Status.BUSY],
        )

        self.stdout.write(f"Scanning for stale nodes (cutoff={cutoff.isoformat()})...")
        self.stdout.write(f"  Found {stale_nodes.count()} stale node(s)")

        for node in stale_nodes:
            task_count = Task.objects.filter(
                assigned_to=node, status__in=[Task.Status.ASSIGNED, Task.Status.RUNNING],
            ).count()

            self.stdout.write(
                f"  Node {node.device_id} ({node.hostname}) — "
                f"last heartbeat: {node.last_heartbeat.isoformat() if node.last_heartbeat else 'never'}, "
                f"tasks to reassign: {task_count}"
            )

            if dry_run:
                continue

            with transaction.atomic():
                # Mark node offline
                old_status = node.status
                node.status = Node.Status.OFFLINE
                node.save(update_fields=["status", "updated_at"])

                # Reassign any in-flight tasks back to queued
                reassigned_tasks = Task.objects.filter(
                    assigned_to=node,
                    status__in=[Task.Status.ASSIGNED, Task.Status.RUNNING],
                )
                for task in reassigned_tasks:
                    task.status = Task.Status.QUEUED
                    task.assigned_to = None
                    task.save(update_fields=["status", "assigned_to", "updated_at"])

                # Audit trail
                log_event(
                    actor_type="system",
                    actor_id="detect_stale_nodes",
                    action="node.timeout",
                    resource_type="node",
                    resource_id=str(node.id),
                    details={
                        "device_id": node.device_id,
                        "hostname": node.hostname,
                        "old_status": old_status,
                        "last_heartbeat": node.last_heartbeat.isoformat() if node.last_heartbeat else None,
                        "tasks_reassigned": task_count,
                    },
                )
                for task in reassigned_tasks:
                    log_event(
                        actor_type="system",
                        actor_id="detect_stale_nodes",
                        action="task.reassign",
                        resource_type="task",
                        resource_id=str(task.id),
                        details={
                            "from_node": node.device_id,
                            "to_status": "queued",
                        },
                    )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run — no changes applied"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Processed {stale_nodes.count()} stale node(s)"))
