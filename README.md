# DTask — Distributed Task Orchestration Platform

Turn a local network of machines into a cooperative task-execution cluster. A **Django-based master** accepts jobs, splits them into sub-tasks, and assigns them to **autonomous Python agents** running on any LAN-connected device. Agents execute, report results, and the master aggregates — no cloud dependency, no Docker required.

---

## Architecture

```
┌──────────────────────┐      REST/WS         ┌──────────────────────────────┐
│   AGENT (Python)     │ ◄──────────────────► │   CONTROL PLANE (Django)     │
│   ┌───────────────┐  │                      │   ┌──────────────────────┐   │
│   │ Agent Core    │  │                      │   │ Django REST API      │   │
│   │ Transport     │──┤                      │   │ Channels (WS)        │   │
│   │ Executor      │  │                      │   │ Orchestrator         │   │
│   │ Discovery     │  │                      │   │ Scheduler Engine     │   │
│   └───────────────┘  │                      │   │ Node Registry        │   │
└──────────────────────┘                      │   │ Security/Auth        │   │
                                              │   │ Admin UI             │   │
                                              │   └──────────────────────┘   │
                                              └──────────────┬───────────────┘
                                                             │
                                              ┌──────────────▼───────────────┐
                                              │   DATA LAYER                 │
                                              │   ┌──────────────────────┐   │
                                              │   │ SQLite / PostgreSQL  │   │
                                              │   ├──────────────────────┤   │
                                              │   │ django-q2 (queue)    │   │
                                              │   └──────────────────────┘   │
                                              └──────────────────────────────┘
```

**Master (Django):** 4 apps — `nodes` (device management), `orchestration` (job/task lifecycle), `security` (auth + audit), `health` (liveness/readiness).

**Agent (Python):** Modular components — `agent_core` (state machine, registration, heartbeat), `transport` (HTTP/WS client), `executor` (plugin-based runner), `discovery` (UDP broadcast for LAN master discovery), `config` (YAML + env overrides).

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 5, Django REST Framework, Django Channels |
| Database | SQLite (dev) / PostgreSQL 16 (prod) |
| Task Queue | django-q2 (ORM-backed, no Redis needed) |
| Agent | Python 3.13, requests, websocket-client, PyInstaller |
| Discovery | UDP broadcast (LAN) |
| Frontend | Django Admin (v1) |

---

## Features

- **Master-Slave topology** — one control plane, many agents
- **6 built-in workload types** — file processing, image processing, checksum/hash, data transformation (CSV/JSON/XML), inline Python execution, chunked numerical computation
- **Plugin system** — drop-in `.py` handlers with auto-discovery
- **Smart scheduling** — 4-dimension scoring (capability match, resource availability, health, reliability)
- **UDP LAN discovery** — agents auto-find the master with no manual configuration
- **Windows service support** — agents run as background services via NSSM
- **Standalone agent executable** — PyInstaller builds a ~12 MB `.exe`, no Python runtime needed
- **Job splitting + result aggregation** — large jobs auto-split, results merged
- **Enrollment key auth** — simple secure node onboarding
- **Stale node detection** — automatic task reassignment on failure
- **Full REST API** — 20+ endpoints for cluster management
- **~217 passing tests** — backend + agent

---

## Quick Start

### Prerequisites
- Python 3.10+ (3.13 recommended)
- Git

### Backend (Master)

```powershell
cd platform/master
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

Create an enrollment key:
```powershell
python manage.py shell -c "from security.models import EnrollmentKey; EnrollmentKey.objects.create(key='demo-key', is_active=True)"
```

### Agent (Development)

```powershell
cd platform/agent
pip install -r requirements.txt
python main.py --enrollment-key demo-key --master-url http://localhost:8000
```

### Agent (Standalone .exe)

```powershell
cd platform/agent
pip install pyinstaller
build_exe.bat --onefile
# Output: dist\dtask-agent.exe
```

Deploy to target machines — no Python needed.

### Agent as Windows Service

```powershell
.\dist\dtask-agent.exe --install-service --enrollment-key demo-key --master-url http://192.168.1.100:8000
```

---

## Project Structure

```
007/
├── docs/                    # All documentation
│   ├── VISION.md            # Elevator pitch & scope
│   ├── ARCHITECTURE.md      # System architecture & data flows
│   ├── PROTOCOL.md          # Full API contract & state machines
│   ├── WORKLOADS.md         # Workload type definitions
│   ├── ROADMAP.md           # 10-phase development plan
│   ├── PROGRESS.md          # Phase completion tracker
│   ├── INSTALLATION.md      # Build, deploy, CI/CD
│   ├── DEPLOY_WINDOWS.md    # Windows deployment guide
│   ├── VERIFICATION.md      # E2E test walkthrough
│   ├── diagrams/            # Architecture diagrams
│   ├── phases/              # Per-phase design docs
│   └── strategies/          # Multi-master & failover strategies
├── platform/
│   ├── agent/               # Python agent application
│   │   ├── main.py          # Entry point
│   │   ├── agent_core/      # State machine, registration, heartbeat
│   │   ├── transport/       # HTTP/WS client
│   │   ├── executor/        # Plugin-based task runner + 6 handlers
│   │   ├── discovery/       # UDP broadcast LAN discovery
│   │   ├── config/          # YAML config loader
│   │   ├── plugins/         # Third-party plugin examples
│   │   └── tests/           # 66+ agent tests
│   ├── master/              # Django backend
│   │   ├── config/          # Django settings, URLs, ASGI/WSGI
│   │   ├── nodes/           # Device registration & cluster management
│   │   ├── orchestration/   # Job/task lifecycle & scheduling engine
│   │   ├── security/        # Auth, audit logging, enrollment
│   │   ├── health/          # Liveness & readiness endpoints
│   │   └── manage.py
│   └── venvs/               # Virtual environments
└── .opencode/               # AI development tooling
```

---

## API Overview

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/nodes/register/` | Device enrollment |
| PUT | `/api/v1/nodes/{id}/activate/` | Activate node |
| POST | `/api/v1/nodes/{id}/heartbeat/` | Report status |
| POST | `/api/v1/clusters/{id}/join/` | Join cluster |
| POST | `/api/v1/jobs/` | Create job (auto-splits) |
| GET | `/api/v1/jobs/{id}/progress/` | Job progress |
| GET | `/api/v1/tasks/assign/?node_id=` | Poll for next task |
| POST | `/api/v1/tasks/{id}/result/` | Submit result |
| GET | `/health/` | Liveness check |
| GET | `/ready/` | Readiness check |

Full contract in [docs/PROTOCOL.md](docs/PROTOCOL.md).

---

## Development Status

| Phase | Area | Status |
|---|---|---|
| 0 | Product definition & architecture | ✅ |
| 1 | Django backend, models, API, admin | ✅ |
| 2 | Python agent, registration, heartbeat | ✅ |
| 3 | LAN discovery & cluster formation | ✅ |
| 4 | Job orchestration & task splitting | ✅ |
| 5 | Scheduling intelligence (scoring engine) | ✅ |
| 6 | Security, audit, stale node detection | ✅ |
| 7 | Plugin system & workload registry | ✅ |
| 8 | Multi-master readiness & health endpoints | ✅ |
| 9 | Go/Rust agent rewrite | ⏳ Pending |

---

## Testing

```powershell
# Backend (root of platform/master)
python manage.py test

# Agent (root of platform/agent)
python -m pytest
```

~217 tests total, all passing.
