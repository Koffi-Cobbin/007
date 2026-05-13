# Phase 2 — Device Agent & Enrollment

> **Completed:** 2026-05-12  
> **Effort:** M (3–4 weeks)  
> **Status:** ✅ Complete

---

## Goal

Build a lightweight Python agent that runs on each device and connects to the Django control plane.

## Deliverables

### Agent Project Structure

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
│   └── lan.py                           # UDP broadcast discovery (Phase 3 scaffold)
└── tests/
    ├── test_state_machine.py            # 14 tests — all state transitions
    ├── test_registration.py             # 6 tests — register, re-register, invalid keys, token persistence
    ├── test_scheduler.py                # 8 tests — start/stop, heartbeat, task polling, callbacks
    ├── test_discovery.py                # 7 tests — UDP broadcast, listener, fallback
    └── test_executor.py                 # 18 tests — all 6 workload type handlers
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

## Key Flows

### Registration Flow
1. Agent loads config (YAML + env overrides)
2. State: `offline` → `enrolling`
3. `POST /nodes/register/` with device_id, enrollment_key, capabilities
4. Receives `node_id`, `token`, `heartbeat_interval_seconds`
5. Token persisted to disk (`agent_data/agent_token.json`)
6. `PUT /nodes/{id}/activate/` → state: `active`

### Heartbeat Cycle
1. Timer fires every `heartbeat_interval` seconds (default: 30)
2. `POST /nodes/{id}/heartbeat/` with status, current_load, resources
3. Backend updates `last_heartbeat` and returns acknowledgement
4. On `401`: token may have expired → re-register

### Task Polling
1. Timer fires every `poll_interval` seconds (default: 5)
2. `GET /tasks/assign/?node_id=...`
3. If task received → state: `busy`, execute via runner
4. If 204 → state: `idle`, wait for next poll

## State Machine

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

## Configuration

`agent.yaml`:
```yaml
master:
  url: ""
  discovery_port: 42069
  discovery_timeout: 3.0

device:
  id: ""
  token_path: "agent_data/agent_token.json"

heartbeat_interval_seconds: 30
poll_interval_seconds: 5
task_timeout_seconds: 300
max_retries: 3

workload_types: []
```

All values overridable via `DTASK_*` environment variables or CLI flags.

## Test Results

```
Ran 53 tests in 1.30s
OK
```

| Test File | Tests | What's Covered |
|---|---|---|
| `test_state_machine.py` | 14 | All valid + invalid state transitions, guards |
| `test_registration.py` | 6 | Register, re-register, invalid keys, token persistence |
| `test_scheduler.py` | 8 | Start/stop, heartbeat, task polling, callbacks |
| `test_discovery.py` | 7 | UDP broadcast, listener, fallback to manual |
| `test_executor.py` | 18 | All 6 workload type handlers |

### Acceptance Criteria

| Criterion | Status | Notes |
|---|---|---|
| Device can join and receive a token | ✅ | Registration flow complete with token persistence |
| Device can periodically report it is alive | ✅ | Timer-based heartbeat every 30s |
| System stores node capability and status data | ✅ | Capabilities sent during registration; status updated via heartbeat |
| Agent can reconnect after temporary network loss | ✅ | 401 detection triggers re-registration; heartbeat retry on connection errors |

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **YAML config** | Human-readable, hierarchical, supports env overrides |
| **threading.Timer** | Simple non-blocking periodic execution without asyncio |
| **Token persisted to disk** | Agent can restart without re-registering if token is still valid |
| **State machine guards** | Invalid transitions raise exceptions — catches bugs early |
| **psutil optional** | Falls back gracefully if psutil not installed |
| **No stubs remain** | All 6 workload handlers are production-ready |

## Post-Release Fixes

| # | Fix | File | Description |
|---|---|---|---|
| 1 | `token_path` type coercion | `agent_core/registration.py` | `os.path.join()` returns `str` but code expected `pathlib.Path` — wrapped in `Path()` constructor |
| 2 | Empty `device_id` in YAML | `config/settings.py` | `agent.yaml` has `device_id: ""` which overrode computed hostname default — strip empty values before `setdefault()` |

## Test Coverage Summary

Tests cover:
- **State machine**: All transitions (valid + invalid) with guard conditions
- **Registration**: Happy path, re-registration, invalid enrollment key, token file persistence
- **Scheduler**: Timer start/stop, heartbeat dispatch, task polling, callback invocation
- **All 6 workload handlers**: checksum, file_processing, image_processing, data_transform, python_execution, numerical

Run with:
```bash
cd platform/agent
pip install -r requirements.txt
python -m pytest tests/ -v
```

## Known Gaps

| # | Item | Severity | Deferred To |
|---|---|---|---|
| 1 | No token-based auth on endpoints | Low | Phase 6 |
| 2 | WebSocket routes / ws_client empty | Low | Phase 6 |
| 3 | No agent health check endpoint | Low | Phase 6 |
| 4 | No Windows service / systemd unit | Low | Phase 6 |

## How to Run

```bash
# Terminal 1 — Backend
cd platform/master
python manage.py migrate
python manage.py runserver

# Terminal 2 — Enrollment key
python manage.py shell -c "from security.models import EnrollmentKey; EnrollmentKey.objects.create(key='dev-key', is_active=True)"

# Terminal 3 — Agent
cd platform/agent
python main.py --enrollment-key dev-key --master-url http://localhost:8000
```

## Next

Added discovery and cluster formation in **Phase 3 — Discovery & Cluster Formation**.
