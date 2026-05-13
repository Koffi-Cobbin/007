# Progress Tracker — Distributed Task Orchestration Platform

> **Updated:** 2026-05-13  
> **Current Phase:** Phase 8 complete — ready for Phase 9

---

## Phase Status Overview

| Phase | Status | Effort | Key Deliverables |
|---|---|---|---|
| 0 — Product Definition & Architecture Lock | ✅ Complete | S (1–2 weeks) | VISION, ARCHITECTURE, PROTOCOL, WORKLOADS, ROADMAP, Draw.io diagram |
| 1 — Foundation Backend & Data Model | ✅ Complete | M (3–5 weeks) | Django project, 12 models, REST API, admin, tests (33/33 passing) |
| 2 — Device Agent & Enrollment | ✅ Complete | M (3–4 weeks) | Python agent app, registration, heartbeat, capability reporting, state machine, config |
| 3 — Discovery & Cluster Formation | ✅ Complete | M (3–4 weeks) | UDP broadcast, join/leave API, master election, cluster admin dashboard |
| 4 — Task Model & Basic Orchestration | ✅ Complete | L (4–6 weeks) | Job splitting, 6 workload executors, result aggregation, progress API, capability scheduling |
| 5 — Scheduling Intelligence | ✅ Complete | M (3–4 weeks) | Capability scoring, resource-aware placement, priority queues, health thresholds |
| 6 — Reliability, Security, Observability | ✅ Complete | L (4–6 weeks) | Token auth, stale detection, audit logging, admin dashboard, health endpoint |
| 7 — Workflow Expansion & Plugin System | ✅ Complete | L (4–6 weeks) | Workload registry, plugin interface, schema validation, resource requirements |
| 8 — Multi-Master Readiness | ✅ Complete | L (4–6 weeks) | Failover strategy, state replication plan, election strategy, separation plan, health endpoints, agent fallback |
| 9 — Language Migration (Go/Rust) | ⏳ Pending | XL (6–10 weeks) | Interface stability, migration map |

---

## Phase 0 — Complete ✅

### Deliverables Created

```
docs/
├── VISION.md              # Elevator pitch, v1 scope (IN/OUT), success criteria
├── ARCHITECTURE.md        # Component boundaries, Django vs Agent rules, data flows
├── PROTOCOL.md            # All API endpoints, payload schemas, state machines
├── WORKLOADS.md           # 6 v1 workload types with schemas + deferred types
├── ROADMAP.md             # 10-phase breakdown with effort sizing
└── diagrams/
    └── system-architecture.drawio   # Draw.io architecture diagram
```

### Key Decisions Made

| Decision | Choice |
|---|---|
| **v1 topology** | 1 master (Django) + N slaves (Python agents) |
| **Communication** | REST + WebSocket |
| **Execution model** | Subprocess (no containers) |
| **Discovery** | UDP broadcast + manual join |
| **Workloads** | 6 types: file, image, checksum, data transform, Python, numerical |
| **Database** | SQLite (dev) / PostgreSQL (prod) |
| **Task queue** | django-q2 (database-backed, no Redis needed) |
| **Migration path** | Defined interfaces → Go/Rust in Phase 9 |

### Retrospective Notes

- Phase 0 was pure design — no code, which kept it focused and fast.
- The v1 scope table (IN vs OUT) has been useful for rejecting scope creep during Phase 1 design discussions.
- django-q2 over Redis simplifies the development setup significantly (no external services needed to run the backend).
- SQLite as default means zero-config onboarding for new developers.

---

## Phase 1 — Complete ✅

### Deliverables Created

```
platform/master/
├── manage.py
├── requirements.txt                     # django, djangorestframework, channels, django-q2
├── config/
│   ├── __init__.py
│   ├── settings.py                      # DRF, Channels, django-q2 (ORM broker)
│   ├── urls.py                          # Mounts all 3 apps at /api/v1/ + /admin/
│   ├── asgi.py                          # Channels ASGI stubbed
│   └── wsgi.py                          # Standard WSGI
├── nodes/                               # Device management app
│   ├── models.py                        # Node, NodeCapability, NodeHeartbeat, Cluster
│   ├── serializers.py                   # NodeSerializer, NodeRegistrationSerializer, etc.
│   ├── views.py                         # NodeViewSet (register, activate, heartbeat)
│   ├── urls.py                          # /api/v1/nodes/, /api/v1/clusters/
│   ├── admin.py                         # All models registered
│   └── tests.py                         # 11 tests
├── orchestration/                       # Task execution app
│   ├── models.py                        # Job, Task, TaskAssignment, TaskResult, TaskLog
│   ├── serializers.py                   # JobSerializer, TaskSerializer, TaskAssignSerializer
│   ├── views.py                         # JobViewSet, TaskViewSet (assign, submit_result)
│   ├── urls.py                          # /api/v1/jobs/, /api/v1/tasks/
│   ├── admin.py                         # All models registered
│   └── tests.py                         # 14 tests
└── security/                            # Auth + audit app
    ├── models.py                        # EnrollmentKey, AuditLog, ProtocolVersion
    ├── serializers.py
    ├── views.py                         # CRUD (keys), ReadOnly (logs, versions)
    ├── urls.py                          # /api/v1/enrollment-keys/, etc.
    ├── admin.py
    └── tests.py                         # 8 tests
```

### Test Results

```
Ran 33 tests in 0.140s
OK
```

### Acceptance Criteria Check

| Criterion | Result | Notes |
|---|---|---|
| Node record can be created and updated | ✅ | Registration, activation, heartbeat all working |
| Task record can be created and assigned a state | ✅ | Full state machine: pending → assigned → running → completed/failed/retry |
| Task history is persisted | ✅ | Separate tables for assignments, results, and logs |
| Admin can inspect cluster state | ✅ | Django admin for all models |
| Registration validates enrollment keys | ✅ | Invalid keys return 401; keys are marked inactive after use |
| Task assignment respects availability | ✅ | Returns 204 if no tasks available; assigns atomically |
| Result submission handles retry logic | ✅ | Retry count incremented; task goes to `failed` when max_retries exhausted |
| Duplicate result submissions are idempotent | ✅ | Uses `update_or_create` |

### Key Implementation Details

**Node Registration Flow:**
1. Agent sends `POST /nodes/register/` with `device_id`, `enrollment_key`, optional `capabilities`
2. Backend validates the enrollment key (must exist + be active)
3. Node created in `enrolling` status, capabilities recorded
4. Enrollment key marked inactive and linked to node
5. Response includes `node_id`, `token`, and `heartbeat_interval_seconds`

**Task Assignment Flow:**
1. Agent polls `GET /tasks/assign/?node_id=...`
2. Backend finds first `pending` or `queued` task
3. If found: task → `assigned`, `TaskAssignment` record created, task payload returned
4. If none: `204 No Content` returned

**Result Submission Flow:**
1. Agent sends `POST /tasks/{id}/result/` with `status`, `output`, optional `error`
2. If `completed`: task marked complete, result stored
3. If `failed` + retries remaining: task → `retry` (count incremented)
4. If `failed` + retries exhausted: task → `failed`
5. Uses `update_or_create` so duplicate submissions don't crash

### Django Apps Architecture

```
App: nodes          → Node, NodeCapability, NodeHeartbeat, Cluster
App: orchestration  → Job, Task, TaskAssignment, TaskResult, TaskLog
App: security       → EnrollmentKey, AuditLog, ProtocolVersion
```

Each app has its own `models.py`, `serializers.py`, `views.py`, `urls.py`, `admin.py`, `tests.py`. Clean separation that maps to the architectural boundaries defined in Phase 0.

### django-q2 Configuration

```python
Q_CLUSTER = {
    "name": "orchestrator",
    "orm": "default",
    "retry": 300,
    "timeout": 300,
    "max_attempts": 3,
    "ack_failures": True,
    "poll": 5,
    "catch_up": False,
}
```

Database-backed (no Redis). Polls every 5 seconds. Tasks that fail are retried up to 3 times. Used for async job splitting and task enqueueing in Phase 4.

### Known Gaps / Open Items

| # | Item | Severity | Notes |
|---|---|---|---|
| 1 | No token-based auth on endpoints yet | Low | Tokens are issued during registration but not validated on heartbeat/results yet — deferred to Phase 6 |
| 2 | WebSocket routes are empty | Low | ASGI configured, `asgi.py` has WS router stubbed, no consumer code yet — will be used for live task push in Phase 4+ |
| 3 | No soft-delete on models | Low | All deletions are hard; consider adding `is_active` or `archived_at` for safety later |
| 4 | No pagination customization | Low | Using DRF default pagination (20/page) — sufficient for v1 |

---

## Phase 2 — Complete ✅

### Deliverables Created

```
platform/agent/
├── main.py                              # Entry point — wires together all components
├── requirements.txt                     # requests, pyyaml, websocket-client
├── config/
│   ├── settings.py                      # YAML config loader with env overrides
│   └── agent.yaml                       # Default config file
├── agent_core/
│   ├── state_machine.py                 # NodeState enum + StateMachine with valid transitions
│   ├── registration.py                  # RegistrationFlow: register → activate → store token
│   └── scheduler.py                     # AgentScheduler: periodic heartbeat + task polling
├── transport/
│   └── http_client.py                   # HttpClient wrapping requests (register, heartbeat, poll, result)
├── executor/
│   └── runner.py                        # TaskRunner — dispatches to 6 workload handlers (Phase 4)
├── discovery/
│   └── lan.py                           # UDP broadcast discovery (Phase 3)
└── tests/
    ├── test_state_machine.py            # 14 tests — all state transitions
    ├── test_registration.py             # 6 tests — register, re-register, invalid keys, token persistence
    ├── test_scheduler.py                # 8 tests — start/stop, heartbeat, task polling, callbacks
    ├── test_discovery.py                # 7 tests — UDP broadcast, listener, fallback
    └── test_executor.py                 # 18 tests — all 6 workload type handlers
```

### Test Results

```
Ran 53 tests in 1.30s
OK
```

### Agent Architecture

```
main.py
  ├── config/settings.py         → loads agent.yaml + DTASK_* env overrides
  ├── agent_core/state_machine   → offline → enrolling → active → idle → busy → offline
  ├── agent_core/registration    → POST /nodes/register/ → PUT /nodes/{id}/activate/
  ├── transport/http_client      → REST client with retry + 401 detection
  ├── agent_core/scheduler       → Timer-based heartbeat + task polling loop
  ├── discovery/lan              → UDP broadcast discovery
  ├── executor/runner            → 6 workload type handlers (checksum, file, image, transform, python, numerical)
```

### Key Design Decisions

| Decision | Rationale |
|---|---|
| **YAML config** | Human-readable, hierarchical, supports env overrides |
| **threading.Timer** | Simple non-blocking periodic execution without asyncio |
| **Token persisted to disk** | Agent can restart without re-registering if token is still valid |
| **State machine guards** | Invalid transitions raise exceptions — catches bugs early |
| **psutil optional** | Falls back gracefully if psutil not installed |
| **No stubs remain** | All 6 workload handlers are production-ready |

### How to Run

```bash
# Terminal 1 — start the backend
cd platform/master
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# Terminal 2 — create an enrollment key
python manage.py shell -c "from security.models import EnrollmentKey; EnrollmentKey.objects.create(key='dev-key', is_active=True)"

# Terminal 3 — start the agent
cd platform/agent
pip install -r requirements.txt
python main.py --enrollment-key dev-key --master-url http://localhost:8000
```

### Post-Release Fixes

| # | Fix | File | Description |
|---|---|---|---|
| 1 | `token_path` type coercion | `agent_core/registration.py` | `os.path.join()` returns `str` but code expected `pathlib.Path` — wrapped in `Path()` constructor |
| 2 | Empty `device_id` in YAML | `config/settings.py` | `agent.yaml` has `device_id: ""` which overrode the computed hostname default — strip empty values before `setdefault()` |

### Known Gaps / Open Items

| # | Item | Severity | Notes |
|---|---|---|---|
| 1 | No token-based auth on endpoints | Low | Backend issues tokens but doesn't validate them yet — Phase 6 |
| 2 | WebSocket routes / ws_client empty | Low | ASGI configured, no consumer code — Phase 4 |
| 3 | No agent health check endpoint | Low | Could expose /health for monitoring — defer to Phase 6 |
| 4 | No Windows service / systemd unit | Low | Agent runs as foreground process — add in Phase 6 |

---

## Phase 3 — Complete ✅

### Deliverables Created

**Backend changes (`platform/master/nodes/`):**

| File | Changes |
|---|---|
| `models.py` | Added `cluster` FK, `joined_at`, `is_designated_master` to `Node`; `discovery_port` to `Cluster` |
| `serializers.py` | Added `ClusterDetailSerializer` (with member_count), `NodeJoinSerializer`, `ElectMasterSerializer` |
| `views.py` | Added cluster join/leave/members/elect-master actions on `ClusterViewSet`; added `DiscoveryViewSet` for beacon endpoint |
| `urls.py` | Added `/api/v1/discover/` route |
| `admin.py` | Node list: cluster name + heartbeat freshness badges; Cluster admin: inline member list + member count |
| `tests.py` | 13 new tests: cluster join/leave/members, master election, discovery beacon |

**Agent changes (`platform/agent/`):**

| File | Changes |
|---|---|
| `discovery/lan.py` | Full UDP broadcast implementation — sends JSON beacon to `255.255.255.255:42069`, listens for `discover_ack` responses |
| `main.py` | Discovery integration: if no `--master-url`, try UDP broadcast first; falls back to config |
| `config/agent.yaml` | Added `discovery_port: 42069`, `discovery_timeout: 3.0` |
| `config/settings.py` | Defaults for new discovery config keys |
| `tests/test_discovery.py` | 7 tests: manual URL, broadcast fallback, listener start/stop, discovery info |

### Test Results

```
Backend: 46 tests (24 nodes + 14 orchestration + 8 security)
Agent:   35 tests (14 state machine + 6 registration + 8 scheduler + 7 discovery)
```

### New API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/clusters/{id}/members/` | List cluster members with status, join time, master flag |
| `POST` | `/api/v1/clusters/{id}/join/` | Node joins a cluster |
| `POST` | `/api/v1/clusters/{id}/leave/` | Node leaves (clears master if was master) |
| `POST` | `/api/v1/clusters/{id}/elect-master/` | Designate a node as cluster master |
| `GET` | `/api/v1/clusters/{id}/` | Detail view — includes `member_count` + `member_summary` |
| `GET` | `/api/v1/discover/` | Beacon response — returns cluster master info for UDP |

### Discovery Flow

```
Agent (no master_url)                  LAN                         Master Node
        │                               │                              │
        │  UDP broadcast: {"type":"discover"}                          │
        │ ────────────────────────────► │                              │
        │                               │  forward to master (or respond directly)
        │                               │ ───────────────────────────► │
        │                               │                              │
        │  UDP response: {"type":"discover_ack",                       │
        │    "master_url":"http://10.0.0.5:8000"}                      │
        │ ◄──────────────────────────── │                              │
        │                               │                              │
        │  POST /api/v1/nodes/register/                                │
        │ ──────────────────────────────────────────────────────────►  │
        │  POST /api/v1/clusters/{id}/join/                            │
        │ ──────────────────────────────────────────────────────────►  │
```

### Master Election

In v1, master election is **manual** — an operator or automated process calls `POST /api/v1/clusters/{id}/elect-master/` with a node ID. The designated node gets `is_designated_master=True` and is set as `Cluster.master_node`. A node that leaves the cluster automatically clears the master slot if it was the master.

### Acceptance Criteria Check

| Criterion | Status | How |
|---|---|---|
| A device can find peers on the network | ✅ | UDP broadcast discovery or manual URL |
| A device can join a cluster | ✅ | `POST /clusters/{id}/join/` |
| The cluster can identify one active master | ✅ | `Cluster.master_node` FK + `elect-master/` endpoint |
| Member nodes can be listed from the dashboard | ✅ | Admin inline members + `/members/` API |

### Post-Release Fixes

| # | Fix | File | Description |
|---|---|---|---|
| 1 | `token_path` type coercion | `agent_core/registration.py` | `os.path.join()` returns `str` but code expected `pathlib.Path` — wrapped in `Path()` constructor |
| 2 | Empty `device_id` in YAML | `config/settings.py` | `agent.yaml` has `device_id: ""` which overrode the computed hostname default — strip empty values before `setdefault()` |

---

## Phase 4 — Complete ✅

### Deliverables Created

**Backend — `platform/master/orchestration/`:**

| File | Changes |
|---|---|
| `tasks.py` (new) | `split_job` — django-q2 async task that splits a Job into sub-tasks by type; `_aggregate_job` — auto-completes job when all tasks finish; `_compute_task_chunks` — 6 workload type split strategies |
| `views.py` | `JobViewSet.progress` — progress endpoint with task counts + %; `perform_create` auto-enqueues split_job; `submit_result` triggers aggregation; capability-based scheduling in `assign` |

**Agent — `platform/agent/executor/runner.py`** (replaced stub):

| Handler | Implementation | Strategy |
|---|---|---|
| `checksum` | `hashlib` streaming | SHA-256/MD5 per file, optional expected-hash verification |
| `file_processing` | `shutil` + `gzip` | Copy or compress files to target directory |
| `image_processing` | ImageMagick or Pillow | Resize, convert format, quality setting |
| `data_transform` | Line-based processing | Filter by expression, convert CSV→JSON, partition support |
| `python_execution` | `exec()` + dispatch | Inline code execution with function call, error capture |
| `numerical` | Pure Python | Monte Carlo π, range summation, chunked iteration |

### Test Results

```
Backend: 46 tests (24 nodes + 13 orchestration + 8 security + 1 new tasks)
Agent:   53 tests (14 state machine + 6 registration + 8 scheduler + 7 discovery + 18 executor)
```

### How the Full Pipeline Works

```
User submits job → POST /api/v1/jobs/
                        │
                        ▼ django-q2 async
                   split_job()
                        │
                        ▼
              ┌──────────────────┐
              │  Task 1: file1   │  queued
              │  Task 2: file2   │  queued
              │  Task 3: file3   │  queued
              └──────────────────┘
                        │
                        ▼ Agent polls
                   GET /tasks/assign/
                   (prefers matching capabilities)
                        │
                        ▼
              ┌──────────────────┐
              │  Agent executes  │  subprocess / inline
              │  handler         │
              └──────────────────┘
                        │
                        ▼
                   POST /tasks/{id}/result/
                        │
                        ▼
              ┌──────────────────┐
              │  Task → completed│
              │  _aggregate_job  │  ← django-q2
              │  checks if done  │
              └──────────────────┘
                        │
                   if all done:
                   Job → COMPLETED
```

### Job Progress API

```
GET /api/v1/jobs/{id}/progress/

{
  "job_id": "uuid",
  "status": "active",
  "total_tasks": 10,
  "completed_tasks": 4,
  "failed_tasks": 0,
  "pending_tasks": 6,
  "progress_pct": 40.0
}
```

### Scheduling Priority

| Priority | Task Status | Capability Match |
|---|---|---|
| 1 (highest) | `retry` | ✅ Matches node's `workload_types` |
| 2 | `pending` / `queued` | ✅ Matches node's `workload_types` |
| 3 | `pending` / `queued` | ❌ Any (fallback) |
| 4 (lowest) | `retry` | ❌ Any (fallback) |

### Acceptance Criteria Check

| Criterion | Status | How |
|---|---|---|
| A job can be split into ≥2 sub-tasks | ✅ | Each file/partition/chunk becomes a sub-task |
| Different nodes can complete different sub-tasks | ✅ | Each task is independently assignable |
| Master can collect all results and mark job complete | ✅ | `_aggregate_job` auto-completes when all tasks finish |
| Failed sub-tasks are visible and recoverable | ✅ | Retry logic + scheduling prefers retry tasks |

---

## Phase 5 — Complete ✅

### Deliverables Created

**`platform/master/orchestration/scheduler.py`** (new) — Scoring engine with 4 dimensions:

| Dimension | Weight | What It Measures |
|---|---|---|
| **Capability** | 35% | Workload-type match, CPU cores, memory |
| **Resource** | 35% | Current CPU load, free memory, free disk (from latest heartbeat) |
| **Health** | 20% | Node status (idle > active > busy > degraded), heartbeat freshness |
| **Reliability** | 10% | Historical task success/fail ratio |

**Priority queues added:**
- `high` / `medium` / `low` on both `Job` and `Task` models
- Jobs submitted with `priority` parameter → all sub-tasks inherit it
- `get_assignable_tasks_for_node()` sorts tasks: retry first, then priority DESC, then FIFO

**Enhanced assignment flow (`orchestration/views.py`):**
1. Agent polls with `node_id`
2. Scheduler finds candidate tasks ordered by priority + age
3. For each task, finds all healthy candidate nodes in the cluster
4. Scores each candidate node using the 4-dimension model
5. Assigns to the best node (or skips if another node is >30% better)
6. Response includes `scheduling_score` with full breakdown

**Health thresholds (`scheduler.py`):**
| Condition | Action |
|---|---|
| Status is `offline` or `degraded` | Excluded from candidates |
| Last heartbeat > 5 minutes | Excluded (stale node) |
| Current load ≥ 0.95 | Excluded (overloaded) |
| No capability record for task type | Excluded |

### Files Changed

| File | Changes |
|---|---|
| `orchestration/models.py` | Added `Priority` choices, `priority` field to `Job` and `Task` |
| `orchestration/scheduler.py` (new) | Scoring engine: `score_node_for_task`, `find_best_node`, `get_candidate_nodes`, `get_assignable_tasks_for_node` |
| `orchestration/serializers.py` | Added `priority` to `JobSerializer` and `TaskSerializer` |
| `orchestration/tasks.py` | `split_job` forwards `job.priority` to all sub-tasks |
| `orchestration/views.py` | `assign` uses scheduler; `perform_create` reads job priority |
| `orchestration/tests_scheduler.py` (new) | 28 new tests covering scoring, filtering, priority, integration |
| `orchestration/tests.py` | Existing tests adapted (no regressions) |

### Test Results

```
Backend: 81 tests (24 nodes + 15 orchestration + 28 scheduler + 8 security + 6 priority)
All 81 tests passing.
```

### Acceptance Criteria Check

| Criterion | Status | How |
|---|---|---|
| Tasks are not assigned blindly | ✅ | Scores computed per (node, task) pair; best node wins |
| Heavy tasks prefer stronger devices | ✅ | Capability score rewards more cores + RAM |
| Low-resource or unhealthy devices are avoided | ✅ | Health thresholds exclude degraded/stale/overloaded nodes |
| Scheduling decisions are explainable in logs | ✅ | Scoring breakdown returned in response; skipped tasks logged |
| Tasks ordered by priority | ✅ | High → medium → low; retry tasks first within each tier |

### Configuration Constants (in `scheduler.py`)

| Constant | Default | Description |
|---|---|---|
| `WEIGHTS` | cap 0.35, res 0.35, health 0.20, rel 0.10 | Scoring dimension weights |
| `MAX_HEARTBEAT_AGE_SECONDS` | 300 | Stale node cutoff (5 minutes) |
| `MAX_LOAD` | 0.95 | Load threshold for overloaded exclusion |
| `DEGRADED_STATUSES` | offline, degraded | Statuses excluded from scheduling |

### Key Design Decisions

| Decision | Rationale |
|---|---|
| **Scoring on poll, not pre-computed** | Simpler, always fresh; no need to recompute scores on every heartbeat |
| **70% score ratio threshold** | If this node scores ≥70% of the best, it still gets the task — avoids starvation where weak nodes never get work |
| **Fallback to non-matching tasks** | If no capability-matched task exists, the scheduler falls back to any available task — keeps the system running |
| **Priority at Job + Task level** | Jobs set priority, all sub-tasks inherit it; clean separation of user intent from execution |

---

## Quick Start

```bash
# ── Backend ──
cd platform/master
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# ── Create enrollment key ──
python manage.py shell -c "from security.models import EnrollmentKey; EnrollmentKey.objects.create(key='dev-key', is_active=True)"

# ── Agent ──
cd platform/agent
pip install -r requirements.txt
python main.py --enrollment-key dev-key --master-url http://localhost:8000

# ── Tests ──
python manage.py test nodes orchestration security   # backend (46 tests)
python -m pytest tests/                              # agent (53 tests)
```
