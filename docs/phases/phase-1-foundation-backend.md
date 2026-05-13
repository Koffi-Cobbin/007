# Phase 1 — Foundation Backend & Data Model

> **Completed:** 2026-05-12  
> **Effort:** M (3–5 weeks)  
> **Status:** ✅ Complete

---

## Goal

Create the Django backbone that stores cluster state, nodes, tasks, and results.

## Deliverables

### Django Project Scaffold

```
platform/master/
├── manage.py
├── requirements.txt                 # django, djangorestframework, channels, django-q2
├── config/
│   ├── settings.py                  # DRF, Channels, django-q2 (ORM broker)
│   ├── urls.py                      # Mounts all 3 apps at /api/v1/ + /admin/
│   ├── asgi.py                      # Channels ASGI stubbed
│   └── wsgi.py                      # Standard WSGI
```

### App: `nodes` (Device Management)

| File | Purpose |
|---|---|
| `models.py` | Node, NodeCapability, NodeHeartbeat, Cluster |
| `serializers.py` | NodeSerializer, NodeRegistrationSerializer, etc. |
| `views.py` | NodeViewSet (register, activate, heartbeat) |
| `urls.py` | `/api/v1/nodes/`, `/api/v1/clusters/` |
| `admin.py` | All models registered |
| `tests.py` | 11 tests |

### App: `orchestration` (Task Execution)

| File | Purpose |
|---|---|
| `models.py` | Job, Task, TaskAssignment, TaskResult, TaskLog |
| `serializers.py` | JobSerializer, TaskSerializer, TaskAssignSerializer |
| `views.py` | JobViewSet, TaskViewSet (assign, submit_result) |
| `urls.py` | `/api/v1/jobs/`, `/api/v1/tasks/` |
| `admin.py` | All models registered |
| `tests.py` | 14 tests |

### App: `security` (Auth + Audit)

| File | Purpose |
|---|---|
| `models.py` | EnrollmentKey, AuditLog, ProtocolVersion |
| `serializers.py` | CRUD serializers |
| `views.py` | CRUD (keys), ReadOnly (logs, versions) |
| `urls.py` | `/api/v1/enrollment-keys/`, etc. |
| `admin.py` | All models registered |
| `tests.py` | 8 tests |

## Core Entities (12 Models)

| Entity | App | Description |
|---|---|---|
| `Node` | nodes | Device identity, status, capabilities, enrollment info |
| `NodeCapability` | nodes | Declared capabilities (CPU cores, RAM, workload types) |
| `NodeHeartbeat` | nodes | Periodic status reports |
| `Cluster` | nodes | Cluster membership and configuration |
| `Job` | orchestration | Top-level work unit |
| `Task` | orchestration | Unit of work assigned to a single node |
| `TaskAssignment` | orchestration | Records which node was assigned which task |
| `TaskResult` | orchestration | Output or error produced by task execution |
| `TaskLog` | orchestration | Execution log entries |
| `EnrollmentKey` | security | Pre-shared keys for device enrollment |
| `AuditLog` | security | Immutable log of significant state changes |
| `ProtocolVersion` | security | API version tracking |

## Key Flows

### Node Registration
1. Agent sends `POST /nodes/register/` with `device_id`, `enrollment_key`, optional `capabilities`
2. Backend validates the enrollment key (must exist + be active)
3. Node created in `enrolling` status, capabilities recorded
4. Enrollment key marked inactive and linked to node
5. Response includes `node_id`, `token`, and `heartbeat_interval_seconds`

### Task Assignment
1. Agent polls `GET /tasks/assign/?node_id=...`
2. Backend finds first `pending` or `queued` task
3. If found: task → `assigned`, `TaskAssignment` record created, task payload returned
4. If none: `204 No Content` returned

### Result Submission
1. Agent sends `POST /tasks/{id}/result/` with `status`, `output`, optional `error`
2. If `completed`: task marked complete, result stored
3. If `failed` + retries remaining: task → `retry` (count incremented)
4. If `failed` + retries exhausted: task → `failed`
5. Uses `update_or_create` so duplicate submissions don't crash

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/nodes/register/` | Register a device |
| `PUT` | `/api/v1/nodes/{id}/activate/` | Activate enrolled node |
| `POST` | `/api/v1/nodes/{id}/heartbeat/` | Report node status |
| `GET` | `/api/v1/nodes/` | List nodes |
| `GET` | `/api/v1/nodes/{id}/` | Node detail |
| `GET` | `/api/v1/tasks/assign/` | Poll for task |
| `POST` | `/api/v1/tasks/{id}/result/` | Submit task result |
| `GET` | `/api/v1/tasks/` | List tasks |
| `GET` | `/api/v1/jobs/` | List jobs |
| `POST` | `/api/v1/jobs/` | Create job |
| `GET` | `/api/v1/clusters/` | List clusters |
| `GET` | `/api/v1/enrollment-keys/` | List enrollment keys |
| `GET` | `/api/v1/audit-logs/` | View audit logs |
| `GET` | `/api/v1/protocol-versions/` | List protocol versions |

## django-q2 Configuration

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

Database-backed (no Redis). Polls every 5 seconds. Tasks that fail are retried up to 3 times.

## Test Results

```
Ran 33 tests in 0.140s
OK
```

| App | Tests | What's Covered |
|---|---|---|
| `nodes` | 11 | Node CRUD, registration, activation, heartbeat, capability recording |
| `orchestration` | 14 | Job CRUD, task assignment, result submission, retry logic, idempotency |
| `security` | 8 | Enrollment key CRUD, audit logs, protocol versions |

### Acceptance Criteria

| Criterion | Status | Notes |
|---|---|---|
| Node record can be created and updated | ✅ | Registration, activation, heartbeat all working |
| Task record can be created and assigned a state | ✅ | Full state machine: pending → assigned → running → completed/failed/retry |
| Task history is persisted | ✅ | Separate tables for assignments, results, and logs |
| Admin can inspect cluster state | ✅ | Django admin for all models |
| Registration validates enrollment keys | ✅ | Invalid keys return 401; keys are marked inactive after use |
| Task assignment respects availability | ✅ | Returns 204 if no tasks available; assigns atomically |
| Result submission handles retry logic | ✅ | Retry count incremented; task goes to `failed` when max_retries exhausted |
| Duplicate result submissions are idempotent | ✅ | Uses `update_or_create` |

## Test Coverage Summary

At this phase, tests cover:
- **Model creation** and string representations
- **API endpoints** (happy path for each: register, activate, heartbeat, assign, submit_result)
- **Error cases** (invalid enrollment key, duplicate device_id, nonexistent node, invalid status)
- **Retry logic** (fresh retry-count, exhausted retries)
- **Idempotency** (duplicate result submissions don't crash)

Run with:
```bash
cd platform/master
python manage.py test nodes orchestration security
```

## Known Gaps

| # | Item | Severity | Deferred To |
|---|---|---|---|
| 1 | No token-based auth on endpoints | Low | Phase 6 |
| 2 | WebSocket routes are empty | Low | Phase 4+ |
| 3 | No soft-delete on models | Low | Future |
| 4 | No pagination customization | Low | Future |

## Key Decisions

| Decision | Rationale |
|---|---|
| **3 Django apps** (nodes, orchestration, security) | Clean separation that maps to architectural boundaries |
| **django-q2 with ORM broker** | No Redis dependency; zero-config for development |
| **DRF ViewSets** | Rapid REST API development with minimal boilerplate |
| **UUID primary keys** | Agent-safe (no sequential IDs); works in distributed context |
| **`update_or_create` for results** | Natural idempotency for duplicate submissions |

## Next

Built the agent in **Phase 2 — Device Agent & Enrollment**.
