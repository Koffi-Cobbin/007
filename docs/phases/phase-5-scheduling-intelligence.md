# Phase 5 — Scheduling Intelligence

> **Completed:** 2026-05-13  
> **Effort:** M (3–4 weeks)  
> **Status:** ✅ Complete

---

## Goal

Make task assignment smarter by scoring node fitness per task using real resource data, rather than simple capability matching.

## Deliverables

| # | Deliverable | Files |
|---|---|---|
| 1 | Weighted scoring engine (4 dimensions) | `orchestration/scheduler.py` |
| 2 | Priority queues (high/medium/low) | `orchestration/models.py`, `orchestration/serializers.py` |
| 3 | Health threshold filtering | `orchestration/scheduler.py` |
| 4 | Resource-aware placement | `orchestration/views.py` (refactored `assign`) |
| 5 | Scoring breakdown in API response | `orchestration/views.py` |
| 6 | Priority inheritance (Job → sub-tasks) | `orchestration/tasks.py` |
| 7 | Test suite (28 new tests) | `orchestration/tests_scheduler.py` |

## Scoring Model

```
score = (capability × 0.35) + (resource × 0.35) + (health × 0.20) + (reliability × 0.10)
```

| Dimension | Weight | Inputs |
|---|---|---|
| **Capability** | 35% | Workload type match (0.5 base), CPU cores, RAM |
| **Resource** | 35% | Current CPU load, free memory fraction, free disk fraction |
| **Health** | 20% | Node status (idle=1.0, active=0.8, busy=0.5), heartbeat freshness |
| **Reliability** | 10% | Historical task success/fail ratio (neutral=0.5 with no data) |

## Health Thresholds

| Condition | Action |
|---|---|
| Node status is `offline` or `degraded` | Excluded from candidates |
| Last heartbeat > 300 seconds (5 min) | Excluded (stale) |
| Current load ≥ 0.95 | Excluded (overloaded) |
| No capability record for required task type | Excluded |

## Priority Queues

- Three levels: `high`, `medium` (default), `low`
- Jobs accept `priority` parameter in POST payload
- All sub-tasks inherit the job's priority during `split_job`
- Assignment order: retry tasks → priority DESC → FIFO within same priority

## API Changes

### Job Creation
```json
POST /api/v1/jobs/
{
  "task_type": "checksum",
  "input_payload": {"files": ["a.iso"]},
  "priority": "high"
}
```

### Task Assignment Response (enhanced)
```json
GET /api/v1/tasks/assign/?node_id=<uuid>

{
  "task_id": "uuid",
  "job_id": "uuid",
  "task_type": "checksum",
  "payload": {},
  "priority": "high",
  "deadline_seconds": 300,
  "created_at": "2026-05-13T11:00:00",
  "scheduling_score": {
    "overall": 0.85,
    "breakdown": {
      "capability": 0.90,
      "resource": 0.72,
      "health": 0.95,
      "reliability": 0.80
    }
  }
}
```

## Assignment Flow

1. Agent polls `GET /tasks/assign/?node_id=...`
2. Scheduler queries candidate tasks ordered by priority + age (retry first)
3. For each task, finds all healthy candidate nodes in the cluster
4. Scores every candidate node using the 4-dimension model
5. If polling node scores ≥70% of the best candidate → assign directly
6. If polling node is significantly worse → skip task, log decision, try next
7. When no better node exists (e.g., only one node in cluster) → assign anyway

## Configuration

All tunable constants live at the top of `scheduler.py`:

| Constant | Default | Description |
|---|---|---|
| `WEIGHTS` | cap 0.35, res 0.35, health 0.20, rel 0.10 | Scoring dimension weights |
| `MAX_HEARTBEAT_AGE_SECONDS` | 300 | Stale node cutoff |
| `MAX_LOAD` | 0.95 | Overload exclusion threshold |
| `DEGRADED_STATUSES` | offline, degraded | Excluded node statuses |

## Test Results

```
Ran 98 tests in 0.575s
OK
```

- **45 scheduler tests** (unit + integration + edge case + concurrency + property-based)
- **0 regressions** in existing tests (53 unchanged)

## Test Coverage Summary

Tests are organized into 6 categories. Run all with:

```bash
cd platform/master
python manage.py test nodes orchestration security
```

### 1. Scoring Unit Tests (21 tests)

| Area | Tests | File |
|---|---|---|
| **Capability scoring** | 4 | `tests_scheduler.py::ScoreCapabilityTests` |
| **Resource scoring** | 3 | `tests_scheduler.py::ScoreResourceTests` |
| **Health scoring** | 3 | `tests_scheduler.py::ScoreHealthTests` |
| **Reliability scoring** | 3 | `tests_scheduler.py::ScoreReliabilityTests` |
| **Score node for task** | 2 | `tests_scheduler.py::ScoreNodeForTaskTests` |

Verifies each dimension independently: matching/non-matching types, load levels, health states, history ratios, and the weighted combination formula.

### 2. Scoring Boundary Tests (6 tests)

| Test | What It Validates |
|---|---|
| `test_capability_64_cores_capped_at_one` | 128 cores / 512 GB doesn't exceed 1.0 |
| `test_resource_zero_load_is_perfect` | Load=0.0 + ample resources ≈ 1.0 |
| `test_resource_max_load_is_zero` | Load=1.0 + full memory/disk → floor score |
| `test_health_no_heartbeat_is_moderate` | No heartbeat history → moderate (not 0, not 1) |
| `test_health_zero_age_is_max` | Heartbeat received just now → max freshness |
| `test_health_offline_node_minimal` | Offline status → very low score |

### 3. Score Invariant / Property Tests (3 tests)

| Test | What It Validates |
|---|---|
| `test_overall_score_always_between_0_and_1` | Overall score is always in [0.0, 1.0] |
| `test_all_breakdown_scores_always_between_0_and_1` | Every dimension is in [0.0, 1.0] |
| `test_no_node_strictly_better_scores_lower` | Node strictly better on all dims always scores higher |

### 4. Candidate & Task Selection Tests (10 tests)

| Class | Tests | What It Validates |
|---|---|---|
| `GetCandidateNodesTests` | 6 | Healthy included; degraded, stale, overloaded, wrong-type, outsider excluded |
| `GetAssignableTasksTests` | 4 | Capability match, fallback, retry priority, priority+age ordering |
| `FindBestNodeTests` | 2 | Picks highest scorer; handles empty list |

### 5. Edge Case & Concurrency Tests (8 tests)

| Class | Tests | What It Validates |
|---|---|---|
| `SchedulerEdgeCaseTests` | 4 | All-degraded → empty candidates, all-degraded → 204, single-node cluster always gets task, no capability → no task |
| `SchedulerPriorityComboTests` | 2 | Retry-high beats pending-high, retry-low beats pending-medium |
| `SchedulerConcurrencyTests` | 2 | One task two nodes → not double-assigned, two tasks two nodes → both assigned |

### 6. Integration Tests (7 tests)

| Class | Tests | What It Validates |
|---|---|---|
| `SchedulerIntegrationTests` | 6 | Scoring in response, priority in response, high-before-low ordering, stronger node preference, weak node fallback, job creation with priority |
| `JobPriorityTests` | 2 | Default priority is medium, priority passed in payload |

### Manual / E2E Tests

See `docs/VERIFICATION.md` → **Phase 5 — Scheduling Intelligence E2E** section for 6 manual verification steps covering priority ordering, stronger node preference, degraded exclusion, stale heartbeat handling, overloaded exclusion, and scoring breakdown inspection.

## Practical Example — End-to-End Walkthrough

This walkthrough tests all Phase 5 features: priority queues, scoring breakdowns, stronger node preference, health thresholds, and stale/excluded node handling.

### Prerequisites

You need **3 terminals** and the ability to run 2 agent instances simultaneously.

```bash
# Terminal 1 — Start the backend
cd platform/master
python manage.py migrate
python manage.py runserver

# Terminal 2 — Create cluster, enrollment key, and initial data
cd platform/master
python manage.py shell
```

```python
from security.models import EnrollmentKey
from nodes.models import Cluster

EnrollmentKey.objects.create(key="phase5-demo", is_active=True)
cluster = Cluster.objects.create(name="scheduling-demo")
print(f"Cluster ID: {cluster.id}")
exit()
```

---

### Scenario 1: Priority Queues (High vs Low)

This tests: high-priority jobs are assigned before low-priority jobs, regardless of creation order.

#### Step 1 — Create a low-priority job first, then a high-priority job

```bash
cd platform/master
python manage.py shell
```

```python
from orchestration.models import Job, Task

# Create low-priority job (created first)
low_job = Job.objects.create(
    task_type="checksum", status="active", priority="low",
    input_payload={"files": ["low_priority.iso"]},
)
Task.objects.create(
    job=low_job, task_type="checksum",
    status="queued", priority="low",
    payload={"files": ["low_priority.iso"]},
)

# Create high-priority job (created second — should still be assigned first)
high_job = Job.objects.create(
    task_type="checksum", status="active", priority="high",
    input_payload={"files": ["high_priority.iso"]},
)
Task.objects.create(
    job=high_job, task_type="checksum",
    status="queued", priority="high",
    payload={"files": ["high_priority.iso"]},
)

print(f"Low-priority task created first, high-priority task created second")
exit()
```

#### Step 2 — Start a single agent

```bash
# Terminal 3
cd platform/agent
python main.py --enrollment-key phase5-demo --master-url http://localhost:8000
```

**Expected:** Even though the low-priority task was created first, the agent should receive the **high-priority task first**, because the scheduler orders by `priority DESC` before `created_at ASC`.

```json
// First poll response:
{
  "task_id": "<high-pri-task-uuid>",
  "priority": "high",
  "scheduling_score": { "overall": 0.78, "breakdown": {...} }
}

// Second poll response (after completing the high-pri task):
{
  "task_id": "<low-pri-task-uuid>",
  "priority": "low",
  "scheduling_score": { "overall": 0.78, "breakdown": {...} }
}
```

---

### Scenario 2: Scoring Breakdown in Response

This tests: the `scheduling_score` field is present in every assign response.

```bash
# Poll the assign endpoint directly
curl "http://localhost:8000/api/v1/tasks/assign/?node_id=<agent-node-uuid>"
```

**Expected response includes:**
```json
{
  "task_id": "uuid",
  "priority": "high",
  "scheduling_score": {
    "overall": 0.85,
    "breakdown": {
      "capability": 0.78,
      "resource": 0.92,
      "health": 0.95,
      "reliability": 0.50
    }
  }
}
```

The breakdown tells you exactly why this node was chosen:
- **capability=0.78**: Node supports the workload type with decent hardware
- **resource=0.92**: Node is mostly idle with free memory
- **health=0.95**: Node status is `idle` and heartbeat is fresh
- **reliability=0.50**: No task history yet (neutral score)

---

### Scenario 3: Stronger Node Preference (2 Agents)

This tests: the scheduler assigns tasks to the better-suited node when multiple agents are available.

#### Step 1 — Stop the agent from Scenario 1, then create two agents with different capability profiles

```bash
cd platform/master
python manage.py shell
```

```python
from nodes.models import Node, NodeCapability, NodeHeartbeat, Cluster
from django.utils import timezone

cluster = Cluster.objects.first()

# Strong node — 16 cores, 32 GB RAM, idle
strong = Node.objects.create(
    device_id="workhorse", hostname="workhorse",
    status=Node.Status.IDLE, cluster=cluster,
)
NodeCapability.objects.create(
    node=strong, cpu_cores=16, memory_mb=32768,
    workload_types=["checksum"],
)
NodeHeartbeat.objects.create(
    node=strong, current_load=0.05, status="idle",
    resources={"memory_used_mb": 4096, "disk_free_mb": 200000},
    uptime_seconds=86400,
)

# Weak node — 2 cores, 2 GB RAM, busy
weak = Node.objects.create(
    device_id="netbook", hostname="netbook",
    status=Node.Status.BUSY, cluster=cluster,
)
NodeCapability.objects.create(
    node=weak, cpu_cores=2, memory_mb=2048,
    workload_types=["checksum"],
)
NodeHeartbeat.objects.create(
    node=weak, current_load=0.85, status="busy",
    resources={"memory_used_mb": 1800, "disk_free_mb": 5000},
    uptime_seconds=43200,
)

print(f"Strong node ID: {strong.id}")
print(f"Weak node ID: {weak.id}")
exit()
```

#### Step 2 — Create a single task

```bash
cd platform/master
python manage.py shell
```

```python
from orchestration.models import Job, Task

job = Job.objects.create(task_type="checksum", status="active")
Task.objects.create(
    job=job, task_type="checksum",
    status="queued", payload={"files": ["test.iso"]},
)
print("Created one task")
exit()
```

#### Step 3 — Poll as the weak node first

```bash
curl "http://localhost:8000/api/v1/tasks/assign/?node_id=<weak-node-id>"
```

**Expected:** `204 No Content` — the scheduler sees the strong node is a much better fit (>30% score gap) and skips the weak node.

#### Step 4 — Poll as the strong node

```bash
curl "http://localhost:8000/api/v1/tasks/assign/?node_id=<strong-node-id>"
```

**Expected:** `200 OK` with the task assigned and a high scheduling score.

You can also check the Django server logs for a message like:
```
Skipping task <uuid> for node netbook — score 0.32 vs best 0.91 (node workhorse)
```

---

### Scenario 4: Health Threshold — Degraded Node Exclusion

This tests: a degraded node stops receiving tasks until its status recovers.

```bash
cd platform/master
python manage.py shell
```

```python
from nodes.models import Node

# Mark the strong node as degraded
strong = Node.objects.get(device_id="workhorse")
strong.status = "degraded"
strong.save()
print(f"Marked {strong.device_id} as degraded")
exit()
```

```bash
# Poll with the strong (now degraded) node
curl "http://localhost:8000/api/v1/tasks/assign/?node_id=<strong-node-id>"
```

**Expected:** `204 No Content` — the degraded node is excluded from candidate selection even though it's the only node that could handle the task.

Now recover the node:
```bash
cd platform/master
python manage.py shell
```

```python
from nodes.models import Node
strong = Node.objects.get(device_id="workhorse")
strong.status = "idle"
strong.save()
print(f"Recovered {strong.device_id} — should now receive tasks")
exit()
```

```bash
# Poll again
curl "http://localhost:8000/api/v1/tasks/assign/?node_id=<strong-node-id>"
```

**Expected:** `200 OK` with the task — the node is healthy again and back in the candidate pool.

---

### Scenario 5: Stale Heartbeat Exclusion

This tests: a node with no recent heartbeat is excluded from scheduling.

```bash
cd platform/master
python manage.py shell
```

```python
from nodes.models import Node, NodeHeartbeat
from django.utils import timezone
from datetime import timedelta

strong = Node.objects.get(device_id="workhorse")

# Create a heartbeat from 10 minutes ago (past the 5-minute threshold)
old_hb = NodeHeartbeat.objects.create(
    node=strong, current_load=0.05, status="idle",
    resources={"memory_used_mb": 4096, "disk_free_mb": 200000},
)
# Force it to be old (bypass auto_now_add)
NodeHeartbeat.objects.filter(id=old_hb.id).update(
    received_at=timezone.now() - timedelta(minutes=10)
)
print(f"Set last heartbeat to 10 minutes ago for {strong.device_id}")
exit()
```

```bash
# Poll
curl "http://localhost:8000/api/v1/tasks/assign/?node_id=<strong-node-id>"
```

**Expected:** `204 No Content` — the node's heartbeat is stale (>5 min), so it's excluded.

---

### Scenario 6: Overloaded Node Exclusion

This tests: a node reporting very high load is excluded from scheduling.

```bash
cd platform/master
python manage.py shell
```

```python
from nodes.models import Node, NodeHeartbeat
from django.utils import timezone

strong = Node.objects.get(device_id="workhorse")

# Report very high load
NodeHeartbeat.objects.create(
    node=strong, current_load=0.99, status="busy",
    resources={"memory_used_mb": 32000, "disk_free_mb": 1000},
    uptime_seconds=86400,
)
print(f"Reported load=0.99 for {strong.device_id}")
exit()
```

```bash
# Poll
curl "http://localhost:8000/api/v1/tasks/assign/?node_id=<strong-node-id>"
```

**Expected:** `204 No Content` — the node's load (0.99) exceeds `MAX_LOAD` (0.95), so it's excluded.

After the load drops (new heartbeat with lower load), the node becomes eligible again:
```bash
python manage.py shell
```
```python
from nodes.models import Node, NodeHeartbeat
NodeHeartbeat.objects.create(
    node=Node.objects.get(device_id="workhorse"),
    current_load=0.10, status="idle",
)
print("Reported normal load — node should be eligible again")
exit()
```

---

### Scenario 7: Combined Demo — Priority + 2 Agents + Scoring

This tests: the full scheduling intelligence working together.

1. Create a high-priority task
2. Run 2 agents (one strong, one weak)
3. Watch the strong agent get the high-priority task first
4. Check the scoring breakdown in the response
5. Degrade the strong agent → weak agent starts getting tasks
6. Recover the strong agent → it re-enters the candidate pool

```bash
# Terminal 1 — Backend (already running)

# Terminal 2 — Mark both nodes healthy
cd platform/master
python manage.py shell
```
```python
from nodes.models import Node, NodeCapability, NodeHeartbeat, Cluster
from orchestration.models import Job, Task
from security.models import EnrollmentKey
from django.utils import timezone

cluster = Cluster.objects.first()
EnrollmentKey.objects.create(key="phase5-full-demo", is_active=True)

# Two tasks: one high, one low priority
job = Job.objects.create(task_type="numerical", status="active", priority="high")
Task.objects.create(job=job, task_type="numerical", status="queued",
    priority="high", payload={"total_chunks": 1, "operation": "sum"})
job2 = Job.objects.create(task_type="numerical", status="active", priority="low")
Task.objects.create(job=job2, task_type="numerical", status="queued",
    priority="low", payload={"total_chunks": 1, "operation": "sum"})

print("Ready — high and low priority tasks created, enrollment key: phase5-full-demo")
exit()
```

```bash
# Terminal 3 — Strong node agent
cd platform/agent
python main.py --enrollment-key phase5-full-demo --master-url http://localhost:8000 --device-id workhorse
```

```bash
# Terminal 4 — Weak node agent
cd platform/agent
python main.py --enrollment-key phase5-full-demo --master-url http://localhost:8000 --device-id netbook
```

**Expected behavior:**

| Event | What Happens |
|---|---|
| **Strong agent polls** | Gets the high-priority task with a high scheduling score |
| **Weak agent polls** | Gets `204` — strong node is a better fit |
| **Strong agent completes task** | Next poll gets... nothing (no more high-priority tasks matching) |
| **Strong agent polls again** | Gets `204` — task is high-priority, but weak node is still worse... actually falls to fallback |
| **Mark strong as `degraded`** via shell | Weak agent starts getting tasks |
| **Mark strong as `idle`** via shell | Strong agent re-enters pool on next poll |

### What to Observe in Logs

| Log Message | Meaning |
|---|---|
| `Skipping task <uuid> for node netbook — score X vs best Y (node workhorse)` | Scheduler decided another node is significantly better |
| `Task received: <uuid> (priority=high)` | Agent got a high-priority task |
| `scheduling_score: {"overall": 0.91, ...}` | Scoring breakdown in response |
| `Task completed: <uuid>` | Agent finished and submitted result |
| `aggregate_job: job <uuid> → COMPLETED` | django-q2 aggregated all tasks |

### Cleanup

```bash
# Stop agent processes (Ctrl+C in Terminals 3 and 4)
# Backend can keep running
```

---

## Key Decisions

| Decision | Rationale |
|---|---|
| **Score on poll, not pre-computed** | Simpler, always fresh data; avoids recomputation on every heartbeat |
| **70% score ratio threshold** | Prevents starvation — weak nodes still get work when they're close to the best |
| **Fallback to non-matching tasks** | If no capability-matched task exists, fall back to any available task to keep the system running |
| **Priority at Job + Task level** | Users set priority once on the job; all sub-tasks inherit it consistently |

## Next

Ready for **Phase 6 — Reliability, Security, Observability**.
