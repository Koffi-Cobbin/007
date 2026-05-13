# PROTOCOL.md — API Contracts and State Machines

## API Versioning

All API requests include the API version in the `Accept` header:

```
Accept: application/json; version=1.0
```

Responses include the version in the `Content-Type` header:

```
Content-Type: application/json; version=1.0
```

When breaking changes are required, the version number is incremented. The server supports at least one previous version during a deprecation window.

## Base URL

All endpoints are prefixed with:

```
/api/v1/
```

## Authentication

### Node Token Auth

All agent-facing endpoints (heartbeat, task assign, result submission, activation, health) require a bearer token issued during node enrollment.

```
Authorization: Bearer <node-token>
```

Tokens are stored on the `Node` record and persisted by the agent to disk. Requests with invalid, expired, or missing tokens return `403 Forbidden`. Tokens for nodes in `offline` status are also rejected.

### Admin Auth

Operator/admin endpoints (listing nodes, tasks, jobs, audit logs, enrollment keys) require Django staff session authentication. Use the Django admin login at `/admin/` or include session credentials.

### Public Endpoints (No Auth)

The following endpoints deliberately accept unauthenticated requests:

| Endpoint | Reason |
|---|---|
| `POST /api/v1/nodes/register/` | Uses enrollment key (not bearer token) |
| `GET /api/v1/discover/` | Public LAN discovery beacon |

## Error Response Format

All errors follow a consistent schema:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description",
    "details": {}
  }
}
```

| HTTP Status | Meaning |
|---|---|
| `200 OK` | Success |
| `201 Created` | Resource created |
| `400 Bad Request` | Invalid payload |
| `401 Unauthorized` | Missing or invalid token |
| `404 Not Found` | Resource not found |
| `409 Conflict` | State conflict (e.g., already enrolled) |
| `422 Unprocessable Entity` | Schema validation failure |
| `500 Internal Server Error` | Server-side failure |

---

## Endpoint Catalog

### Node Enrollment

**`POST /api/v1/nodes/register`** — Register a new device with the platform.

*No authentication required (uses enrollment key).*

**Request:**
```json
{
  "device_id": "string (unique, persistent identifier)",
  "hostname": "string",
  "platform": "windows | linux",
  "enrollment_key": "string (pre-shared key)",
  "capabilities": {
    "cpu_cores": 12,
    "memory_mb": 16068,
    "disk_free_mb": 200000,
    "workload_types": ["file_processing", "checksum", "python_execution"],
    "architecture": "AMD64"
  },
  "agent_version": "1.0.0"
}
```

**Response `201 Created`:**
```json
{
  "node_id": "uuid",
  "status": "enrolled",
  "token": "bearer-token-string",
  "heartbeat_interval_seconds": 30
}
```

**Response `409 Conflict`:**
```json
{
  "error": {
    "code": "ALREADY_ENROLLED",
    "message": "Device is already registered. Use PUT /api/v1/nodes/{id}/reactivate to re-enroll."
  }
}
```

---

### Node Activation

**`PUT /api/v1/nodes/{node_id}/activate`** — Mark an enrolled node as active and ready for work.

*Requires bearer token (issued during registration).*

**Request:**
```json
{
  "status": "active"
}
```

**Response `200 OK`:**
```json
{
  "node_id": "uuid",
  "status": "active"
}
```

---

### Heartbeat

**`POST /api/v1/nodes/{node_id}/heartbeat`** — Report node status and current resource usage.

*Requires bearer token.*

**Request:**
```json
{
  "status": "idle | busy | degraded",
  "current_load": 0.35,
  "current_task_id": "uuid | null",
  "resources": {
    "cpu_percent": 35.0,
    "memory_used_mb": 4096,
    "disk_free_mb": 180000
  },
  "uptime_seconds": 86400
}
```

**Response `200 OK`:**
```json
{
  "accepted": true,
  "next_heartbeat_in": 30,
  "pending_tasks": 2
}
```

---

### Create Job

**`POST /api/v1/jobs/`** — Submit a new job. The job is split into sub-tasks asynchronously via django-q2.

*Requires operator authentication.*

**Request:**
```json
{
  "task_type": "checksum | file_processing | image_processing | data_transform | python_execution | numerical",
  "input_payload": {
    "files": ["/path/to/file1", "/path/to/file2"],
    "parameters": {}
  },
  "priority": "high | medium | low"
}
```

`priority` is optional (defaults to `medium`). All sub-tasks inherit the job's priority.

**Response `201 Created`:**
```json
{
  "id": "uuid",
  "status": "pending",
  "task_type": "checksum",
  "priority": "medium",
  "input_payload": {},
  "created_at": "ISO-8601 timestamp"
}
```

---

### Job Progress

**`GET /api/v1/jobs/{job_id}/progress/`** — Get completion status of a job.

*Requires operator authentication.*

**Response `200 OK`:**
```json
{
  "job_id": "uuid",
  "status": "active | completed | failed",
  "total_tasks": 10,
  "completed_tasks": 4,
  "failed_tasks": 0,
  "pending_tasks": 6,
  "progress_pct": 40.0
}
```

---

### Node Health (Phase 6)

**`GET /api/v1/nodes/{node_id}/health`** — Returns a comprehensive health summary for a node.

*Requires bearer token.*

**Response `200 OK`:**
```json
{
  "node_id": "uuid",
  "device_id": "worker-1",
  "hostname": "worker-1.local",
  "status": "idle | active | busy | degraded | offline",
  "is_master": false,
  "last_heartbeat": "ISO-8601 timestamp",
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
  "cluster_id": "uuid | null",
  "cluster_name": "prod | null"
}
```

---

### Poll for Task Assignment

**`GET /api/v1/tasks/assign?node_id={node_id}&capabilities={capability_list}`** — Agent polls for the next available task matching its capabilities.

*Requires bearer token (issued during registration).*

**Response `200 OK` (task available):**
```json
{
  "task_id": "uuid",
  "job_id": "uuid",
  "task_type": "file_processing | image_processing | checksum | data_transform | python_execution | numerical",
  "payload": {
    "input_path": "string | null",
    "input_data": {},
    "parameters": {}
  },
  "priority": "high | medium | low",
  "deadline_seconds": 300,
  "created_at": "ISO-8601 timestamp",
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

**Response `204 No Content` (no task available):**
```
(empty body)
```

---

### Submit Task Result

**`POST /api/v1/tasks/{task_id}/result`** — Report task execution result.

*Requires bearer token.*

**Request (success):**
```json
{
  "status": "completed",
  "output": {
    "output_path": "string | null",
    "output_data": {},
    "summary": {
      "items_processed": 100,
      "bytes_processed": 1048576,
      "duration_seconds": 45.2
    }
  },
  "logs": "string (optional, execution log text)"
}
```

**Request (failure):**
```json
{
  "status": "failed",
  "error": {
    "code": "EXECUTION_TIMEOUT | INVALID_INPUT | INTERNAL_ERROR",
    "message": "Description of what went wrong",
    "traceback": "string (optional)"
  },
  "logs": "string (optional)"
}
```

**Response `200 OK`:**
```json
{
  "accepted": true,
  "next_action": "none | retry"
}
```

---

### List Available Tasks (for operator)

**`GET /api/v1/tasks?status={status}&node_id={node_id}`** — Query task status.

*Requires operator authentication.*

**Response `200 OK`:**
```json
{
  "tasks": [
    {
      "task_id": "uuid",
      "job_id": "uuid",
      "status": "pending | assigned | running | completed | failed | retry",
      "assigned_to": "uuid | null",
      "task_type": "string",
      "created_at": "ISO-8601",
      "completed_at": "ISO-8601 | null"
    }
  ],
  "total": 42,
  "page": 1,
  "page_size": 20
}
```

---

### List Nodes (for operator)

**`GET /api/v1/nodes?status={status}`** — Query node status.

*Requires operator authentication.*

**Response `200 OK`:**
```json
{
  "nodes": [
    {
      "node_id": "uuid",
      "hostname": "string",
      "status": "offline | enrolling | active | idle | busy | degraded",
      "capabilities": {},
      "last_heartbeat": "ISO-8601 | null",
      "uptime_seconds": 86400,
      "tasks_completed": 150,
      "current_load": 0.35
    }
  ],
  "total": 5
}
```

---

## Node State Machine

```
                     ┌──────────┐
                     │  OFFLINE │
                     └────┬─────┘
                          │ discovers / configures master
                          ▼
                   ┌────────────┐
                   │  ENROLLING │  POST /nodes/register
                   └──────┬─────┘
                          │ enrollment approved
                          ▼
                    ┌──────────┐
                    │  ACTIVE  │  PUT /nodes/{id}/activate
                    └────┬─────┘
                         │
                    ┌────┴─────┐
                    │          │
                    ▼          ▼
               ┌───────┐  ┌────────┐
               │ IDLE  │  │ BUSY   │  (executing task)
               └───┬───┘  └───┬────┘
                   │          │
                   │  ┌───────┘
                   │  │ task completes
                   ▼  ▼
               ┌──────────┐
               │ ACTIVE   │
               └────┬─────┘
                    │ heartbeat timeout
                    ▼
               ┌───────────┐
               │ DEGRADED  │  (network issues, high load)
               └─────┬─────┘
                     │
                ┌────┴────┐
                │         │
                ▼         ▼
           ┌────────┐ ┌──────────┐
           │ ACTIVE │ │ OFFLINE  │
           └────────┘ └──────────┘
```

## Task State Machine

```
                     ┌───────────┐
                     │  PENDING  │  (created but not yet queued)
                     └─────┬─────┘
                           │ enqueued
                           ▼
                     ┌───────────┐
                     │  QUEUED   │  (waiting in Redis)
                     └─────┬─────┘
                           │ scheduler assigns to node
                           ▼
                     ┌────────────┐
                     │  ASSIGNED  │  (assigned to a specific node)
                     └─────┬──────┘
                           │ agent acknowledges / starts
                           ▼
                     ┌───────────┐
                     │  RUNNING  │  (executing on agent)
                     └─────┬─────┘
                           │
                    ┌──────┴──────┐
                    │             │
                    ▼             ▼
              ┌──────────┐  ┌──────────┐
              │COMPLETED │  │  FAILED  │
              └──────────┘  └────┬─────┘
                                 │
                            ┌────┴────┐
                            │         │
                            ▼         ▼
                      ┌─────────┐ ┌──────────┐
                      │  RETRY  │ │ CANCELLED│
                      └────┬────┘ └──────────┘
                           │ reassigned
                           ▼
                      ┌───────────┐
                      │  QUEUED   │
                      └───────────┘
```

## Payload Schema Definitions

### Capability Report

Sent during enrollment and periodically updated. Describes what a node can do.

```json
{
  "cpu_cores": 12,
  "cpu_architecture": "AMD64",
  "memory_mb": 16068,
  "disk_free_mb": 200000,
  "workload_types": ["file_processing", "checksum", "python_execution"],
  "os_family": "windows | linux",
  "os_distribution": "Windows 11 Home | Ubuntu 26.04"
}
```

### Task Payload

The unit of work assigned to an agent. Contents vary by workload type.

```json
{
  "task_id": "uuid",
  "job_id": "uuid",
  "task_type": "string",
  "inputs": {
    "files": ["path1", "path2"],
    "parameters": {},
    "data": {}
  },
  "timeout_seconds": 300,
  "max_retries": 3
}
```

### Task Result

```json
{
  "task_id": "uuid",
  "node_id": "uuid",
  "status": "completed | failed | cancelled",
  "output": {},
  "error": {},
  "metrics": {
    "started_at": "ISO-8601",
    "completed_at": "ISO-8601",
    "duration_seconds": 45.2,
    "peak_memory_mb": 256
  },
  "logs": "string"
}
```

## Protocol Compliance Rules

1. Every request and response must include a `Content-Type` with version.
2. Every authenticated request must include a valid `Authorization` header.
3. Unknown fields in requests must be ignored (not rejected) for forward compatibility.
4. Required fields missing from requests must return `422 Unprocessable Entity`.
5. All timestamps must be ISO-8601 format in UTC.
6. All sizes must be in megabytes (MB) unless otherwise specified.
7. Agents must respect the `heartbeat_interval_seconds` returned by the server.
8. Agents must handle `401 Unauthorized` by attempting re-enrollment.
