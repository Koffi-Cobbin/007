# Phase 6 — Reliability, Security, Observability

> **Completed:** 2026-05-13  
> **Effort:** L (4–6 weeks)  
> **Status:** ✅ Complete

---

## Goal

Make the platform trustworthy enough for real use.

## Deliverables

| # | Deliverable | Files |
|---|---|---|
| 1 | Token authentication backend | `security/auth.py` |
| 2 | Auth enforcement on all agent endpoints | `nodes/views.py`, `orchestration/views.py`, `security/views.py` |
| 3 | Audit logging helper + integration | `security/auth.py` (log_event) + views |
| 4 | Stale node detection CLI | `security/management/commands/detect_stale_nodes.py` |
| 5 | Agent health endpoint | `nodes/views.py` (health action) |
| 6 | Admin dashboard enhancements | `nodes/admin.py`, `orchestration/admin.py`, `security/admin.py` |
| 7 | Test suite (31 new tests) | `security/tests.py`, `nodes/tests.py`, `orchestration/tests.py` |

## Token Authentication

**Mechanism:** `Authorization: Bearer <node-token>`

The `NodeTokenAuthentication` backend (DRF `BaseAuthentication` subclass):
1. Reads the `Authorization` header
2. Looks up `Node` by `token` field
3. Rejects if node is `offline` (terminal bad state)
4. Returns `(node_instance, token_string)` on success

**Enforcement per endpoint:**

| Endpoint | Auth Required | Notes |
|---|---|---|
| `POST /nodes/register/` | ❌ | Uses enrollment key |
| `GET /discover/` | ❌ | Public beacon |
| `PUT /nodes/{id}/activate/` | ✅ Bearer | |
| `POST /nodes/{id}/heartbeat/` | ✅ Bearer | |
| `POST /nodes/{id}/capabilities/` | ✅ Bearer | |
| `GET /nodes/{id}/health/` | ✅ Bearer | |
| `GET /tasks/assign/` | ✅ Bearer | |
| `POST /tasks/{id}/result/` | ✅ Bearer | |
| `GET /nodes/` | ✅ Admin | Django staff session |
| `GET /tasks/` | ✅ Admin | Django staff session |
| `GET /jobs/` | ✅ Admin | Django staff session |
| `GET /audit-logs/` | ✅ Admin | Django staff session |

## Audit Logging

**Helper:** `security.auth.log_event(actor_type, actor_id, action, resource_type, resource_id, details)`

**Events logged:**

| Action | Triggered By |
|---|---|
| `node.register` | Node registration |
| `node.activate` | Node activation |
| `node.timeout` | Stale node detection |
| `task.assign` | Task assignment (includes score breakdown) |
| `task.completed` | Successful result submission |
| `task.failed` | Failed result submission |
| `task.reassign` | Task reassigned after node timeout |
| `job.create` | Job creation |

## Stale Node Detection

**Command:** `python manage.py detect_stale_nodes`

| Feature | Detail |
|---|---|
| Default threshold | 300 seconds (5 min) since last heartbeat |
| Configurable | `--max-age 600` (10 min) |
| Dry-run | `--dry-run` to report without modifying |
| What it does | Marks stale nodes `offline`; reassigns their `assigned`/`running` tasks back to `queued` |
| Audit trail | Writes `node.timeout` + `task.reassign` audit log entries |

Designed to be run via cron / Task Scheduler every 5 minutes.

## Agent Health Endpoint

```
GET /api/v1/nodes/{id}/health/
Authorization: Bearer <node-token>
```

**Response:**
```json
{
  "node_id": "uuid",
  "device_id": "worker-1",
  "hostname": "worker-1.local",
  "status": "idle",
  "is_master": false,
  "last_heartbeat": "2026-05-13T12:00:00Z",
  "uptime_seconds": 86400,
  "current_load": 0.15,
  "resources": {
    "cpu_percent": 15.0,
    "memory_used_mb": 4096,
    "disk_free_mb": 80000
  },
  "pending_tasks": 2,
  "tasks_completed": 150,
  "tasks_failed": 3,
  "cluster_id": "uuid",
  "cluster_name": "prod"
}
```

## Admin Dashboard Enhancements

### Nodes Admin
- **Status badges**: colored (`idle`=green, `busy`=orange, `degraded`=red, `offline`=gray)
- **Heartbeat freshness**: green "just now", warning "⚠ 10m ago" for stale
- **Task columns**: pending count, completed count

### Orchestration Admin
- **Job list**: short ID, priority badge (high=red, medium=orange, low=green), task count
- **Task list**: status badges, priority badges, linked job ID, inline assignment info
- **Task results**: colored status, duration column, linked to parent task
- **Task logs**: colored level (info=blue, warn=orange, error=red)

### Security Admin
- **AuditLog**: color-coded actions (register=purple, timeout=red, completed=green), date hierarchy, search
- **EnrollmentKey**: active/used badge, searchable
- **ProtocolVersion**: active/deprecated badge

## Test Results

```
Ran 129 tests in 28.039s
OK
```

| Test Area | App | Tests | What's Covered |
|---|---|---|---|
| **Auth enforcement** | nodes | 10 | Valid token, invalid token, missing token, offline node, admin-only endpoints, registration bypass |
| **Auth enforcement** | orchestration | 5 | Assign requires token, result requires token, admin for list/create |
| **Token auth** | security | 4 | Valid/invalid/missing/offline |
| **Audit log helper** | security | 3 | log_event creates entry, multiple entries |
| **Audit log integration** | nodes | 2 | Register writes audit log, activate writes audit log |
| **Audit log integration** | orchestration | 2 | Assign writes audit log, result writes audit log |
| **Stale detection** | security | 7 | Fresh nodes, stale detection, mark offline, task reassign, ignore offline, dry-run, audit trail, custom max-age |
| **Health endpoint** | nodes | 2 | Returns node state, requires auth |
| **Renewed tests** | all | 94 | Existing tests updated with auth headers |

## Key Decisions

| Decision | Rationale |
|---|---|
| **DRF custom auth backend** | Node tokens are stored on `Node.token`, not Django's auth system — simple lookup without migration |
| **403 for invalid tokens** | DRF's `PermissionDenied` catches failed auth; 403 is sufficient for all auth failure scenarios |
| **Enrollment keys stay unauthenticated** | Registration is the bootstrap flow — no token exists yet |
| **Admin endpoints use session auth** | Staff users use Django admin, not bearer tokens — same as any Django app |
| **Stale detection as CLI command** | Cron-compatible; no always-on background process needed |
| **Audit log as helper function** | Single call site (`log_event()`) ensures consistent format; no risk of raw `AuditLog.objects.create()` calls |
| **Admin UI enhancements via format_html** | Zero JS, zero external dependencies — pure Django admin |

## Deferred Items

| Feature | Reason |
|---|---|
| HTTPS/WSS encryption | Requires cert management — operational concern |
| Per-node cryptographic identity | Certificate management is complex — Phase 9 ready |
| WebSocket consumers | No real-time push use case yet |
| Structured JSON logging | Simple Django logging config change |
| Webhook alerting | No monitoring system to integrate with |

## Acceptance Criteria Check

| Criterion | Status | How |
|---|---|---|
| Unauthorized nodes cannot join the cluster | ✅ | Enrollment key validation |
| Unauthorized nodes cannot perform actions | ✅ | Bearer token on all agent endpoints |
| Invalid/offline node tokens rejected | ✅ | Token lookup fails → 403 |
| Task history is auditable from admin | ✅ | AuditLog populated; admin with colored actions + date_hierarchy |
| System recovers from node offline | ✅ | `detect_stale_nodes` → offline + reassign |
| Scheduling decisions explainable | ✅ | Score in assign response + audit log |

## Next

Ready for **Phase 7 — Workflow Expansion & Plugin System**.
