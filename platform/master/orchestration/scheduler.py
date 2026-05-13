"""
Scheduling intelligence engine — capability scoring and resource-aware placement.

Provides:
  - Node fitness scoring (capability, resource, health, reliability)
  - Priority-based task ordering
  - Health threshold filtering
  - Best-node selection for a given task

Phase 5 — Scheduling Intelligence
"""

import logging
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

# ── Scoring weights ──────────────────────────────────────────────────────────
# These control how much each factor influences the final node fitness score.
WEIGHTS = {
    "capability": 0.35,
    "resource": 0.35,
    "health": 0.20,
    "reliability": 0.10,
}

# ── Health thresholds ────────────────────────────────────────────────────────
MAX_HEARTBEAT_AGE_SECONDS = 300  # 5 minutes
MAX_LOAD = 0.95
DEGRADED_STATUSES = ("offline", "degraded")

# ── Priority ordering ────────────────────────────────────────────────────────
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


# ═════════════════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════════════════


def score_node_for_task(node, task) -> dict:
    """Compute a multi-factor fitness score for *node* executing *task*.

    Returns a dict with the overall score (0.0–1.0) and a breakdown::

        {
            "overall": 0.74,
            "breakdown": {
                "capability": 0.85,
                "resource": 0.60,
                "health": 0.90,
                "reliability": 0.50,
            },
        }
    """
    breakdown = {
        "capability": round(_score_capability(node, task), 4),
        "resource": round(_score_resource(node), 4),
        "health": round(_score_health(node), 4),
        "reliability": round(_score_reliability(node), 4),
    }
    overall = sum(
        breakdown[dim] * WEIGHTS[dim] for dim in WEIGHTS
    )
    return {"overall": round(overall, 4), "breakdown": breakdown}


def find_best_node(task, candidate_nodes):
    """Score all *candidate_nodes* and return the one best suited for *task*.

    Returns ``(best_node, score_dict)`` or ``(None, None)`` if the list is
    empty.
    """
    best = None
    best_score = None
    for node in candidate_nodes:
        score = score_node_for_task(node, task)
        if best is None or score["overall"] > best_score["overall"]:
            best = node
            best_score = score
    return best, best_score


def get_candidate_nodes(task_type, cluster):
    """Return all healthy, capable nodes in *cluster* for the given
    *task_type*.

    A node is considered a candidate when all of the following are true:

    * Its status is NOT in ``DEGRADED_STATUSES``.
    * Its latest heartbeat (if any) is no older than
      ``MAX_HEARTBEAT_AGE_SECONDS``.
    * It has a ``NodeCapability`` record that contains *task_type* in its
      ``workload_types``.
    * Its latest reported ``current_load`` is below ``MAX_LOAD``.
    """
    from nodes.models import Node

    now = timezone.now()
    cutoff = now - timedelta(seconds=MAX_HEARTBEAT_AGE_SECONDS)

    # We need subqueries for latest heartbeat + latest capability.
    # Using a Python filter for simplicity / readability; the data volumes
    # in v1 are small enough that the DB round-trips are negligible.
    nodes = (
        Node.objects
        .filter(cluster=cluster)
        .exclude(status__in=DEGRADED_STATUSES)
        .prefetch_related("capabilities", "heartbeats")
    )

    candidates = []
    for node in nodes:
        cap = _get_latest_capability(node)
        if not cap or task_type not in (cap.workload_types or []):
            continue

        hb = _get_latest_heartbeat(node)
        if hb is None:
            # No heartbeat yet — fresh node, still candidate
            candidates.append(node)
            continue

        if hb.received_at and hb.received_at < cutoff:
            continue  # stale heartbeat

        load = hb.current_load or 0.0
        if load >= MAX_LOAD:
            continue

        candidates.append(node)

    return candidates


def get_assignable_tasks_for_node(node, supported_types: list[str]):
    """Return tasks this node is eligible for, ordered by priority then age.

    Sort order:
      1. Retry tasks matching capabilities (highest urgency)
      2. Pending/queued tasks matching capabilities
      3. Any pending/queued task (fallback)
      4. Any retry task (last resort)

    Within each group, secondary sort is priority DESC then age ASC (FIFO).
    """
    from .models import Task

    if not supported_types:
        supported_types = []

    base = Task.objects.filter(
        Q(status="retry") | Q(status__in=["pending", "queued"]),
    )

    # Collect tasks from all buckets to build a complete ordered list.
    # Each task gets a (group, priority_order, created_at) sort tuple so that
    # retry tasks always sort before pending tasks, regardless of priority level.
    seen_ids = set()
    all_tasks = []

    def _add_tasks(qs, group):
        """Append tasks from *qs* that haven't been seen yet, with *group*."""
        result = []
        for t in qs:
            if t.id not in seen_ids:
                seen_ids.add(t.id)
                result.append((t, group))
        return result

    GROUP_RETRY_CAP = 0   # highest urgency
    GROUP_PENDING_CAP = 1
    GROUP_PENDING_ANY = 2
    GROUP_RETRY_ANY = 3   # last resort

    # 1) Retry matching capabilities
    if supported_types:
        qs = base.filter(task_type__in=supported_types, status="retry")
        all_tasks.extend(_add_tasks(qs, GROUP_RETRY_CAP))

    # 2) Pending/queued matching capabilities
    if supported_types:
        qs = base.filter(task_type__in=supported_types, status__in=["pending", "queued"])
        all_tasks.extend(_add_tasks(qs, GROUP_PENDING_CAP))

    # 3) Any pending/queued (fallback)
    qs = base.filter(status__in=["pending", "queued"])
    all_tasks.extend(_add_tasks(qs, GROUP_PENDING_ANY))

    # 4) Any retry (last resort)
    qs = base.filter(status="retry")
    all_tasks.extend(_add_tasks(qs, GROUP_RETRY_ANY))

    # Sort by group first, then priority, then age
    all_tasks.sort(key=lambda item: (
        item[1],                      # group (retry cap = 0, pending cap = 1, …)
        PRIORITY_ORDER.get(item[0].priority, 1),  # priority within group
        item[0].created_at or timezone.now(),      # age within same priority
    ))
    return [t for t, _ in all_tasks]


# ═════════════════════════════════════════════════════════════════════════════
# Internal scoring functions  (all return 0.0 – 1.0)
# ═════════════════════════════════════════════════════════════════════════════


def _score_capability(node, task) -> float:
    """Score based on workload-type match and hardware capability.

    - 0.5 base if the node supports the task's workload type.
    - Additional 0.0–0.5 based on CPU cores and memory headroom vs. typical
      task needs.
    """
    cap = _get_latest_capability(node)
    if not cap:
        return 0.0

    # Workload-type match
    if task.task_type not in (cap.workload_types or []):
        return 0.0
    type_score = 0.5

    # Hardware score  — more cores & RAM → higher score (capped at 0.5)
    cores = cap.cpu_cores or 1
    mem = cap.memory_mb or 1024
    hardware = min(0.5, (cores / 64) * 0.3 + (mem / 131072) * 0.2)  # 64 cores / 128 GB = max
    return min(1.0, type_score + hardware)


def _score_resource(node) -> float:
    """Score based on current resource availability (latest heartbeat).

    Measures:
      - CPU load (lower is better)
      - Free memory fraction
      - Free disk fraction
    """
    hb = _get_latest_heartbeat(node)
    if hb is None:
        return 1.0  # No data → optimistic (fresh node)

    resources = hb.resources or {}
    load = hb.current_load or 0.0

    load_score = max(0.0, 1.0 - load)                    # 0% load = 1.0, 100% = 0.0
    mem_free = resources.get("memory_used_mb", 0)
    mem_total = (_get_latest_capability(node).memory_mb or 1024) if _get_latest_capability(node) else 1024
    mem_free_frac = max(0.0, 1.0 - (mem_free / max(mem_total, 1)))

    disk_free = resources.get("disk_free_mb", 0)
    disk_total = (_get_latest_capability(node).disk_free_mb or 1024) if _get_latest_capability(node) else 1024
    disk_free_frac = min(1.0, disk_free / max(disk_total, 1))

    return round((load_score * 0.5) + (mem_free_frac * 0.3) + (disk_free_frac * 0.2), 4)


def _score_health(node) -> float:
    """Score based on node status and heartbeat freshness.

    Status weighting:
      idle   = 1.0
      active = 0.8
      busy   = 0.5
      other  = 0.0
    """
    status_scores = {"idle": 1.0, "active": 0.8, "busy": 0.5}
    status_score = status_scores.get(node.status, 0.0)

    hb = _get_latest_heartbeat(node)
    if hb is None or hb.received_at is None:
        freshness = 0.5  # No heartbeat → moderate score
    else:
        age_seconds = (timezone.now() - hb.received_at).total_seconds()
        freshness = max(0.0, 1.0 - (age_seconds / MAX_HEARTBEAT_AGE_SECONDS))

    return round((status_score * 0.6) + (freshness * 0.4), 4)


def _score_reliability(node) -> float:
    """Score based on historical task success rate.

    Ratio of completed tasks vs total assigned tasks for this node.
    A node with no history gets 0.5 (neutral).
    """
    from .models import TaskResult

    completed = TaskResult.objects.filter(
        task__assigned_to=node, status="completed"
    ).count()
    failed = TaskResult.objects.filter(
        task__assigned_to=node, status="failed"
    ).count()
    total = completed + failed

    if total == 0:
        return 0.5  # neutral — no track record
    return round(completed / total, 4)


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


def _get_latest_capability(node):
    """Return the most recent NodeCapability or ``None``."""
    try:
        return node.capabilities.order_by("-reported_at").first()
    except Exception:
        return None


def _get_latest_heartbeat(node):
    """Return the most recent NodeHeartbeat or ``None``."""
    try:
        return node.heartbeats.order_by("-received_at").first()
    except Exception:
        return None


def _task_sort_key(task):
    """Sort key: priority order ASC, then created_at ASC (oldest first)."""
    return (PRIORITY_ORDER.get(task.priority, 1), task.created_at or timezone.now())
