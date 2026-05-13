# Control-Plane Separation Plan

> **Phase:** 8  
> **Status:** Draft — 2026-05-13  
> **Audience:** Developers preparing for service decomposition

---

## 1. Current Monolithic Architecture

```
                ┌──────────────────────────────────────┐
                │          Django Monolith             │
                │                                      │
                │  ┌──────────┐  ┌──────────────────┐  │
                │  │  REST    │  │   Scheduler      │  │
                │  │  API     │  │   Engine         │  │
                │  │          │  │                  │  │
                │  │  nodes   │  │  score_node()    │  │
                │  │  orch.   │  │  find_best()     │  │
                │  │  security│  │  get_candidates()│  │
                │  └──────────┘  └──────────────────┘  │
                │                                      │
                │  ┌──────────┐  ┌──────────────────┐  │
                │  │  Admin   │  │  django-q2       │  │
                │  │  UI      │  │  (task queue)    │  │
                │  └──────────┘  └──────────────────┘  │
                │                                      │
                │  ┌──────────────────────────────────┐│
                │  │  Database (SQLite/PostgreSQL)    ││
                │  └──────────────────────────────────┘│
                └──────────────────────────────────────┘
```

## 2. Decomposition Targets

### Service A: API Gateway + Admin UI

**Responsibility:** Request routing, authentication, admin dashboard

**Technologies:** Django (keep), DRF, Django admin

**Stays:**
- `nodes/` app (node management endpoints)
- `security/` app (enrollment keys, audit logs)
- `orchestration/` views (job/task CRUD)
- Django admin UI
- Authentication / authorization

**Key extraction point when migrating:** The API service must become a thin routing layer that validates auth and proxies to backend services.

### Service B: Scheduler Engine

**Responsibility:** Task-to-node matching, scoring, placement decisions

**Technologies:** Python (standalone), Go (future)

**Would extract:**
- `orchestration/scheduler.py` →
- `orchestration/views.py` (assign logic) → `scheduler_service/`

**Contract:** REST API + shared database (or gRPC for higher throughput)

```
POST /scheduler/find-candidates
{
  "task_id": "uuid",
  "task_type": "checksum",
  "priority": "high",
  "required_resources": {"min_cpu_cores": 4}
}

Response:
{
  "candidates": [
    {"node_id": "uuid", "score": 0.91, "breakdown": {...}},
    {"node_id": "uuid", "score": 0.45, "breakdown": {...}}
  ]
}
```

### Service C: Task Queue / Orchestrator

**Responsibility:** Job splitting, task enqueuing, result aggregation

**Technologies:** django-q2 (keep), Celery (future), Temporal (future)

**Stays as django-q2 for v1.** When the system outgrows database-backed queues:

```
django-q2 (ORM)  ─►  Celery (Redis/RabbitMQ)  ─►  Temporal (durable execution)

Migration path:
  1. Replace Q_CLUSTER broker from "orm" to "redis"
  2. Extract into standalone worker processes
  3. Replace with Temporal workflows for complex orchestration
```

### Service D: Agent Gateway

**Responsibility:** WebSocket management, heartbeat ingestion, live agent communication

**Technologies:** Django Channels (current), Go/WebSocket (future)

**Current state:** ASGI configured, Channels installed, no consumers implemented.
When WebSocket support is added, it should be a standalone service from day one.

## 3. Extraction Roadmap

### Phase 8 (Current) — Define Boundaries

```
Goal: Identify clean extraction points
─► This document ─► done
─► Clean interface contracts ─► already defined in PROTOCOL.md
─► Scheduler already modular in scheduler.py ─► easy extraction candidate
```

### Phase 9 — API Gateway Separation (Documentation)

```
Goal: Document how to extract API routing
─► Define service contracts (OpenAPI)
─► Implement request routing layer
─► Deploy as separate process (optional)
```

### Post-v1 — Scheduler Extraction

```
Goal: Extract scheduler as standalone service
─► Copy scheduler.py to new service
─► Add REST/gRPC interface
─► Add Redis cache for node state
─► Connect API gateway to scheduler service
```

## 4. Interface Contracts (Already Defined)

The following contracts are already versioned and documented. They are the extraction boundaries:

| Contract | Defined In | Extracted Into |
|---|---|---|
| Task payload schema | `PROTOCOL.md` | Service B → Service C |
| Node capability schema | `PROTOCOL.md` | Service A → Service B |
| Result format | `PROTOCOL.md` | Agent → Service C |
| Assign request/response | `PROTOCOL.md` | Agent → Service B |
| Scoring breakdown | `scheduler.py` | Service B |

## 5. Shared State Analysis

Before extracting any service, analyze shared state dependencies:

```
                 ┌──────────────────────────────────────┐
                 │          Shared Database              │
                 │                                      │
                 │  Node  ◄─── Scheduler reads          │
                 │  NodeCapability ◄─── Scheduler reads │
                 │  NodeHeartbeat ◄─── Scheduler reads  │
                 │  Task ◄─── Scheduler reads/writes    │
                 │  TaskAssignment ◄─── Scheduler writes│
                 │  Job ◄─── API writes, Scheduler reads│
                 │  Cluster ◄─── Scheduler reads        │
                 └──────────────────────────────────────┘
```

**Observation:** Nearly every service needs DB access. True separation requires either:
1. **Shared DB** (simpler, works for moderate scale) — all services connect to the same PostgreSQL
2. **Event-driven** (more scalable) — services communicate via events, own their data

**Recommendation for v1.5:** Shared DB with read-replicas. The scheduler reads node state from a read-replica and writes task assignments to the primary.

## 6. Migration Strategy

```
Phase 8 (now)         ─►  Define contracts, document plans
Phase 9               ─►  API documentation, interface stability
v1.5                  ─►  Extract scheduler as standalone
                        ─►  Add Redis caching for node state
                        ─►  Replace django-q2 with Celery
v2                    ─►  Full service decomposition
                        ─►  Event-driven architecture
                        ─►  Temporal for orchestration
                        ─►  Go/Rust for scheduler + gateway
```

Each extraction step is reversible — the monolith can absorb the service back if the extraction proves premature.

## 7. Key Risks

| Risk | Mitigation |
|---|---|
| **Premature decomposition** | Phase 8 only documents; actual extraction deferred |
| **Shared DB coupling** | All models are in one DB; introduce read-replicas before extracting |
| **Scheduler needs low latency** | In-memory scoring is fast; network call adds 1-5ms — acceptable for v1 |
| **Agent connection management** | Keep API gateway in monolith until WebSocket is needed |
