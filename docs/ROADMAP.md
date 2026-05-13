# ROADMAP.md — Distributed Task Orchestration Platform

## Overview

Ten phases from product definition through language migration. Phases 0–6 form the MVP and deliver a working distributed orchestration engine. Phases 7–9 add advanced features, scale, and prepare for performance-critical reimplementation in Go or Rust.

**Estimated total effort:** 9–15 months for a small team (1–3 engineers).

---

## Legend

| Symbol | Meaning |
|---|---|
| ✅ **Done** | Phase complete |
| 🔜 **Current** | Active or next to start |
| ⏳ **Pending** | Not yet started |
| 🧠 **Design only** | Documentation / architecture, no code |

---

## Phase 0 — Product Definition and Architecture Lock

| | |
|---|---|
| **Type** | 🧠 Design only |
| **Effort** | S (1–2 weeks) |
| **Status** | ✅ Done |

### Goal
Define the platform clearly enough to avoid building the wrong system.

### Decisions Made
- Task orchestration means: a master splits jobs into independent sub-tasks and assigns them to capable slave nodes over LAN
- First supported workload types: file processing, batch image processing, checksum/hash, data transformation, Python function execution, chunked numerical processing
- Network assumption: LAN-first, single master, multiple slaves
- Django owns the control plane; Python owns the agent
- REST + WebSocket for agent communication; subprocess for execution

### Deliverables
- `docs/VISION.md`
- `docs/ARCHITECTURE.md`
- `docs/PROTOCOL.md`
- `docs/WORKLOADS.md`
- `docs/ROADMAP.md`
- `docs/diagrams/system-architecture.drawio`

### Acceptance Criteria
- The team can explain the system in one paragraph
- The first version's boundaries are clear
- No vague "do everything" scope remains

---

## Phase 1 — Foundation Backend and Data Model

| | |
|---|---|
| **Effort** | M (3–5 weeks) |
| **Status** | ✅ Done |

### Goal
Create the Django backbone that stores cluster state, nodes, tasks, and results.

### Core Entities
Device / Node, NodeCapability, NodeHeartbeat, Cluster, Job, Task, TaskAssignment, TaskResult, TaskLog, EnrollmentKey, AuditLog, ProtocolVersion

### Deliverables
- Django project scaffold (`platform/master/`)
- Database schema with migrations for all core entities
- Admin interface for inspecting nodes and tasks
- REST API for cluster objects (CRUD for nodes, tasks, jobs)
- API documentation draft
- Basic test suite for models and serializers

### Acceptance Criteria
- A node record can be created and updated via the API
- A task record can be created and assigned a state
- Task history is persisted and queryable
- Admin can inspect the cluster state from the Django admin UI

---

## Phase 2 — Device Agent and Enrollment

| | |
|---|---|
| **Effort** | M (3–4 weeks) |
| **Status** | ✅ Done |

### Goal
Build a lightweight Python agent that runs on each device and connects to the Django control plane.

### Deliverables
- Agent application scaffold (`platform/agent/`)
- Registration endpoint (Phase 1 extension)
- Heartbeat endpoint (Phase 1 extension)
- Capability reporting payload format
- Node state machine implementation
- Local agent configuration format (YAML/JSON)
- Enrollment key flow (first security token)

### Acceptance Criteria
- A device can join the system and receive a token
- A device can periodically report it is alive
- The system stores node capability and status data
- The agent can reconnect after temporary network loss

---

## Phase 3 — Discovery and Cluster Formation

| | |
|---|---|
| **Effort** | M (3–4 weeks) |
| **Status** | ✅ Done |

### Goal
Allow devices on the same network to find each other and form a cluster.

### Discovery Methods (v1)
- UDP broadcast discovery on LAN
- Manual join via config file (point agent at master IP)

### Master Election (v1)
- Simple: manual master selection via config, or designated master flag

### Deliverables
- Discovery module on the agent (UDP broadcast)
- Join workflow (discover → register → activate)
- Cluster membership list API
- Master selection logic
- Node trust/approval flow
- Cluster status dashboard (Django admin extension)

### Acceptance Criteria
- A device can find peers on the network
- A device can join a cluster
- The cluster can identify one active master
- Member nodes can be listed from the dashboard

---

## Phase 4 — Task Model and Basic Orchestration

| | |
|---|---|
| **Effort** | L (4–6 weeks) |
| **Status** | ✅ Done |

### Goal
Introduce real work: the master can split jobs into sub-tasks, assign them to slaves, and receive results.

### v1 Workload Types
1. File processing (copy, compress, transform)
2. Batch image processing (resize, convert, watermark)
3. Checksum / hash jobs (MD5, SHA-256)
4. Data transformation (CSV, JSON, XML)
5. Python function execution
6. Chunked numerical processing

### Deliverables
- Job / Task / SubTask model (Phase 1 extension)
- Task queue mechanism (django-q2, database-backed)
- Scheduling engine v1 (capability-based matching)
- Assignment and completion APIs
- Task retry logic (configurable retries)
- Result aggregation logic
- Job progress reporting API

### Acceptance Criteria
- A job can be split into at least 2 sub-tasks
- Different nodes can complete different sub-tasks
- The master can collect all results and mark the job complete
- Failed sub-tasks are visible and recoverable (retry or reassign)

---

## Phase 5 — Scheduling Intelligence and Resource Awareness

| | |
|---|---|
| **Effort** | M (3–4 weeks) |
| **Status** | ✅ Done |

### Goal
Make assignment smarter by using device resources and workload requirements.

### Scheduling Inputs
- CPU core count, free RAM, current CPU load
- GPU availability (detection only — no scheduling in v1)
- Battery level for portable devices
- Network quality
- Node trust level, task priority, task dependency graph

### Deliverables (implemented)
| # | Deliverable | File |
|---|---|---|
| 1 | Capability scoring system (rank nodes by fitness for a task) | `orchestration/scheduler.py` |
| 2 | 4-dimension weighted scoring model (capability, resource, health, reliability) | `orchestration/scheduler.py` |
| 3 | Priority queues (high/medium/low) on Job + Task | `orchestration/models.py` |
| 4 | Resource-aware placement rules | `orchestration/views.py` |
| 5 | Node health thresholds (stale, overloaded, degraded exclusion) | `orchestration/scheduler.py` |
| 6 | Scoring breakdown in assign response | `orchestration/views.py` |
| 7 | Priority inheritance (Job → sub-tasks) | `orchestration/tasks.py` |
| 8 | 28 new tests (unit + integration) | `orchestration/tests_scheduler.py` |

### Acceptance Criteria
| Criterion | Status | How |
|---|---|---|
| Tasks are not assigned blindly | ✅ | 4-dimension scoring per (node, task) pair |
| Heavy tasks prefer stronger devices | ✅ | Capability score rewards cores + RAM |
| Low-resource or unhealthy devices are avoided | ✅ | Health thresholds: stale/overloaded/degraded excluded |
| Scheduling decisions are explainable in logs | ✅ | Scoring breakdown in API response; skipped tasks logged |
| Tasks ordered by priority | ✅ | High → medium → low; retry first within each tier |

---

## Phase 6 — Reliability, Security, and Observability

| | |
|---|---|
| **Effort** | L (4–6 weeks) |
| **Status** | ✅ Done |

### Goal
Make the platform trustworthy enough for real use.

### Deliverables (implemented)

| # | Deliverable | File |
|---|---|---|
| 1 | Token auth backend (Bearer token → Node lookup) | `security/auth.py` |
| 2 | Auth enforcement on all agent endpoints | `nodes/views.py`, `orchestration/views.py`, `security/views.py` |
| 3 | Audit logging helper + integrated into register/activate/assign/result | `security/auth.py` (log_event) |
| 4 | Stale node detection management command | `security/management/commands/detect_stale_nodes.py` |
| 5 | Agent health endpoint | `nodes/views.py` (health action) |
| 6 | Admin dashboard: status badges, task counts, colored audit log | `nodes/admin.py`, `orchestration/admin.py`, `security/admin.py` |

### Deferred
- Encrypted transport (HTTPS/WSS) — requires certificate management
- Per-node cryptographic identity — Phase 9 ready
- WebSocket consumers — ASGI stays stubbed
- Structured JSON logging — Django config change
- Webhook alerting — no monitoring system to integrate with yet

### Acceptance Criteria

| Criterion | Status | How |
|---|---|---|
| Unauthorized nodes cannot join the cluster | ✅ | Enrollment key validation (already worked) |
| Unauthorized nodes cannot perform actions | ✅ | Bearer token required on all agent endpoints (heartbeat, assign, result, health, activate) |
| Invalid/offline node tokens rejected | ✅ | Token lookup fails → 403; offline node → 403 |
| Task history is auditable from admin UI | ✅ | AuditLog populated on register, activate, assign, result; admin with color-coded actions + date_hierarchy |
| System can recover from node dropping offline | ✅ | `detect_stale_nodes` marks stale nodes offline + reassigns tasks; --dry-run for safety |
| Operators can see why a task was placed on a node | ✅ | Scheduling score in assign response (Phase 5); audit log records score breakdown |

---

## Phase 7 — Workflow Expansion and Plugin System

| | |
|---|---|
| **Effort** | L (4–6 weeks) |
| **Status** | ⏳ Pending |

### Goal
Support richer workloads without rewriting the core platform.

### Deliverables
- Plugin interface for task handlers
- Workload registry (versioned task-type definitions)
- Versioned task schemas (schema evolution)
- Task-type capability matching in the scheduler
- Sandboxing policy (execution isolation)
- Optional container-based execution support (Docker executor)

### Acceptance Criteria
- A new task type can be added without changing the entire system
- Nodes can advertise support for specific workload kinds
- The scheduler can route based on task type

---

## Phase 8 — Multi-Master Readiness and Advanced Coordination

| | |
|---|---|
| **Effort** | L (4–6 weeks) |
| **Status** | ✅ Done |

### Goal
Prepare the system for growth beyond a single always-on master.

### Deliverables (implemented)

| # | Deliverable | Files |
|---|---|---|
| 1 | Master Failover Strategy | `docs/strategies/master-failover.md` |
| 2 | State Replication Plan | `docs/strategies/state-replication.md` |
| 3 | Master Election Strategy | `docs/strategies/master-election.md` |
| 4 | Control-Plane Separation Plan | `docs/strategies/control-plane-separation.md` |
| 5 | Backend health/readiness endpoints | `health/views.py` |
| 6 | Agent fallback master URL support | `agent/main.py`, `config/agent.yaml` |

### Acceptance Criteria

| Criterion | Status | How |
|---|---|---|
| Survive master loss with limited disruption | ✅ | Warm-standby procedure documented; agent auto-failover via `--fallback-url` |
| Another node can take control | ✅ | Manual failover procedure; `detect_stale_nodes` for task recovery |
| Not trapped in single-node assumption | ✅ | Separation plan shows extraction path for scheduler, queue, and gateway |

### Strategy Docs Index
- [Master Failover](docs/strategies/master-failover.md) — failure scenarios, warm-standby architecture, procedure
- [State Replication](docs/strategies/state-replication.md) — PostgreSQL streaming, django-q2 HA, split-brain prevention
- [Master Election](docs/strategies/master-election.md) — lease-based algorithm, priority-based fallback
- [Control-Plane Separation](docs/strategies/control-plane-separation.md) — 4 service targets, extraction roadmap

---

## Phase 9 — Performance Scaling and Language Migration Path

| | |
|---|---|
| **Effort** | XL (6–10 weeks) |
| **Status** | ⏳ Pending |

### Goal
Prepare to move critical components to Go or Rust without breaking the platform.

### What May Move to Go/Rust
- Node agent (rewrite for lower resource usage)
- Scheduler engine (higher throughput)
- Discovery service (faster LAN scanning)
- Heartbeat service (higher frequency)
- High-throughput messaging layer
- Worker runtime

### What Stays in Django
- Admin dashboard
- User management
- Task/job metadata management
- Orchestration APIs
- Audit/history views
- Operator workflows

### Deliverables
- Interface stability plan (ensure contracts don't change)
- Protocol versioning policy
- Migration map (which module, when, why)
- Service decomposition strategy
- Benchmark targets for future services

### Acceptance Criteria
- You can identify which modules can be swapped out later
- The project has no hard dependency on Python for every moving part
- The platform can evolve without a full rewrite

---

## Recommended Build Order (MVP)

The optimal path to a working system:

```
Phase 0  ─►  Phase 1  ─►  Phase 2  ─►  Phase 3  ─►  Phase 4  ─►  Phase 5  ─►  Phase 6
 (design)    (backend)    (agent)      (discovery)  (tasks)     (scheduler) (security)
```

Each phase builds on the previous one. A working distributed orchestration engine exists at the end of Phase 4. Phases 5 and 6 add intelligence and hardening.

## Risk Notes

| Risk | Mitigation |
|---|---|
| Scope creep in Phase 4 (too many workload types) | Start with 1–2 types before expanding to all 6 |
| Agent portability (Windows vs Linux paths, subprocess differences) | Test both OSes from Phase 2 onward |
| Django performance at scale | Keep the option to extract services into Go/Rust (Phase 9) |
| Security is complex | Start with token auth (Phase 2), add encryption (Phase 6), iterate |
