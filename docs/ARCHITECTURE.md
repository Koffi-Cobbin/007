# ARCHITECTURE.md — System Architecture

## System Overview

The platform is split into two major subsystems communicating over HTTP/REST and WebSocket:

```
┌──────────────────────┐      REST/WS         ┌────────────────────────┐
│   AGENT (Python)     │ ◄──────────────────► │   CONTROL PLANE        │
│   ┌───────────────┐  │                      │   (Django Backend)     │
│   │ Agent Core    │  │                      │   ┌─────────────────┐  │
│   │ Transport     │──┤                      │   │ Django REST API │  │
│   │ Executor      │  │                      │   │ Channels (WS)   │──┤
│   │ Discovery     │  │                      │   │ Orchestrator    │  │
│   └───────────────┘  │                      │   │ Scheduler       │  │
└──────────────────────┘                      │   │ Node Registry   │  │
                                              │   │ Security/Auth   │  │
                                              │   │ Admin UI        │  │
                                              │   └─────────────────┘  │
                                              └───────────┬─────────────┘
                                                          │
                                              ┌───────────▼─────────────┐
                                              │   DATA LAYER            │
                                              │   ┌──────────────────┐  │
                                              │   │ SQLite (dev)     │  │
                                              │   │ PostgreSQL (prod)│  │
                                              │   │ (source of truth)│  │
                                              │   ├──────────────────┤  │
                                              │   │ django-q2        │  │
                                              │   │ (task queue)     │  │
                                              │   └──────────────────┘  │
                                              └─────────────────────────┘
```

See `diagrams/system-architecture.drawio` for the visual diagram.

## Component Boundaries

### Control Plane (Django) — Owns

| Component | Responsibility |
|---|---|
| **Django REST API** | Exposes all external API endpoints for agent registration, heartbeat, task assignment, result submission |
| **Django Channels** | WebSocket endpoint for live agent communication and status updates |
| **Orchestrator** | Job lifecycle management: create job, split into sub-tasks, track completion, aggregate results |
| **Scheduler Engine** | Matches tasks to capable nodes based on resource availability and capability reporting |
| **Node Registry** | Stores node identity, capabilities, status, and heartbeat history |
| **Security & Auth** | Enrollment token validation, per-node identity, token-based authentication |
| **Admin UI** | Django admin interface for operators to inspect cluster state, nodes, tasks, and history |

### Agent (Python) — Owns

| Component | Responsibility |
|---|---|
| **Agent Core** | Registration flow, heartbeat scheduling, configuration management, state machine |
| **Transport Layer** | HTTP client for REST API calls, WebSocket client for live channel communication |
| **Executor** | Subprocess-based task runner; manages task lifecycle (pull → run → report result) |
| **Discovery Module** | LAN discovery via UDP broadcast; manual join via configuration |

### Data Layer

| Store | Role |
|---|---|
| **SQLite** (development) | Zero-config database for local development; ships with Python |
| **PostgreSQL** (production) | Production source of truth: nodes, jobs, tasks, results, heartbeats, audit logs, enrollment records |
| **django-q2** | Django-native task queue using the database as its broker; manages task scheduling, retries, and failure handling |

## Django vs Agent Boundary Rules

These rules define what belongs in each subsystem. Violating these creates coupling that makes future language migration harder.

### Belongs in the Control Plane (Django)

- Persistent storage of cluster state
- Job and task metadata management
- Scheduling decisions and task-to-node assignment
- Authentication and enrollment authorization
- Admin and operator interfaces
- Audit logging and task history
- API contract enforcement (request validation, versioning)

### Belongs in the Agent

- Execution of assigned tasks (subprocess runner)
- Local resource monitoring (CPU, memory, disk)
- Heartbeat generation and status reporting
- LAN discovery broadcasts and responses
- Local task state tracking (running, completed, failed)
- Reconnection and retry logic for network failures

### Shared Contracts (Neither Owns Alone)

- **Task payload schema** — Defined and versioned in `PROTOCOL.md`; validated on both sides
- **Capability report schema** — Agent collects; control plane stores and queries
- **Node state machine** — Both sides respect the same states and transitions
- **Result format** — Agent produces; control plane validates and stores

## Data Flow Sequences

### Node Enrollment

```
Agent                    Control Plane              PostgreSQL
  │                           │                         │
  │  POST /api/v1/nodes/      │                         │
  │  { device_id, caps }      │                         │
  │ ───────────────────────►  │                         │
  │                           │  INSERT node (pending)   │
  │                           │ ─────────────────────►   │
  │                           │                         │
  │  { status: "enrolled",    │                         │
  │    token: "..." }          │                         │
  │ ◄───────────────────────  │                         │
  │                           │                         │
  │  PUT /api/v1/nodes/{id}/  │                         │
  │  activate                 │                         │
  │ ───────────────────────►  │  UPDATE node → active   │
  │                           │ ─────────────────────►   │
```

### Heartbeat Cycle

```
Agent                         Control Plane
  │                                │
  │ POST /api/v1/nodes/{id}/       │
  │ heartbeat                      │
  │ { status: "idle", load: 0.3 }  │
  │ ───────────────────────────►   │
  │                                │  UPDATE node
  │                                │  last_seen, status
  │ 200 OK                         │
  │ ◄───────────────────────────   │
  │                                │
  │ (repeat every N seconds)       │
```

### Task Lifecycle

```
Operator / API          Control Plane              django-q2 Queue        Agent
     │                       │                         │                  │
     │ POST /api/v1/jobs     │                         │                  │
     │ ──────────────────►   │                         │                  │
     │                       │  Split job → sub-tasks  │                  │
     │                       │  ──► INSERT tasks       │                  │
     │                       │  ──► async() via        │                  │
     │                       │      django-q2          │                  │
     │                       │ ──────────────────────►  │                  │
     │                       │                         │                  │
     │                       │                         │ django-q2        │
     │                       │                         │ schedules &      │
     │                       │                         │ manages task     │
     │                       │                         │                  │
     │                       │  Agent pulls next task: │                  │
     │                       │  GET /api/v1/tasks/      │                  │
     │                       │  assign                  │                  │
     │                       │ ◄─────────────────────── │                  │
     │                       │                         │                  │
     │                       │  { task_id, payload }    │                  │
     │                       │ ────────────────────────►│                  │
     │                       │                         │                  │
     │                       │                         │  Execute task     │
     │                       │                         │  (subprocess)     │
     │                       │                         │       │           │
     │                       │                         │  POST result      │
     │                       │ ◄────────────────────────│────────────────── │
     │                       │                         │                  │
     │                       │  UPDATE task → complete │                  │
     │                       │  AGGREGATE results      │                  │
     │                       │                         │                  │
     │  Job status update     │                         │                  │
     │ ◄──────────────────── │                         │                  │
```

## Core Entities (Database Schema Overview)

Detailed schema is defined in Phase 1, but the architecture presumes these entities:

| Entity | Description |
|---|---|
| `Node` | Device identity, status, capabilities, enrollment info |
| `NodeHeartbeat` | Periodic status reports from each node |
| `NodeCapability` | Declared capabilities (CPU cores, RAM, workload types) |
| `Cluster` | Cluster membership and configuration |
| `Job` | Top-level work unit; a user submits a job |
| `Task` | A unit of work assigned to a single node |
| `TaskAssignment` | Records which node was assigned which task and when |
| `TaskResult` | Output or error produced by task execution |
| `TaskLog` | Execution log entries for a task |
| `EnrollmentKey` | Pre-shared keys or tokens for device enrollment |
| `AuditLog` | Immutable log of significant state changes |

## Tech Stack (v1)

| Layer | Technology | Purpose |
|---|---|---|
| **Backend framework** | Django | Control plane, API, admin |
| **API layer** | Django REST Framework | Versioned REST endpoints |
| **Live updates** | Django Channels | WebSocket communication |
| **Primary database** | SQLite (dev) / PostgreSQL (prod) | Persistent state, source of truth |
| **Task queue** | django-q2 | Async task scheduling, retries, failure handling |
| **Agent language** | Python | Rapid agent development |
| **Agent transport** | `requests` + `websockets` | HTTP/WS client |
| **Execution** | `subprocess` | Task runner (v1) |
| **Frontend** | Django admin | Operator dashboard (v1) |

## Key Architectural Decisions

| Decision | Rationale |
|---|---|
| Django for v1 control plane | Fastest path to a solid, testable foundation; built-in auth, admin, ORM |
| SQLite for dev, PostgreSQL for prod | SQLite requires zero setup for development; PostgreSQL for production scale |
| django-q2 for task queue | Django-native, database-backed, no external dependency; supports scheduling, retries, and failure handling out of the box |
| REST + WebSocket for agent communication | REST for request/response (registration, heartbeat, results); WebSocket for live task push and status |
| Subprocess execution first | Simplest possible execution model; no container runtime dependency |
| Python agent first | Speed of development; can be rewritten in Go/Rust later with stable contracts |
| LAN-first discovery | Avoids NAT, security, and public-endpoint complexity in v1 |
| Single master in v1 | Avoids consensus protocol complexity until the basic system is proven |
