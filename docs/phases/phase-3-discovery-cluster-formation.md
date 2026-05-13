# Phase 3 — Discovery & Cluster Formation

> **Completed:** 2026-05-12  
> **Effort:** M (3–4 weeks)  
> **Status:** ✅ Complete

---

## Goal

Allow devices on the same network to find each other and form a cluster.

## Deliverables

### Backend Changes (`platform/master/nodes/`)

| File | Changes |
|---|---|
| `models.py` | Added `cluster` FK, `joined_at`, `is_designated_master` to `Node`; `discovery_port` to `Cluster` |
| `serializers.py` | Added `ClusterDetailSerializer` (with member_count), `NodeJoinSerializer`, `ElectMasterSerializer` |
| `views.py` | Added cluster join/leave/members/elect-master actions on `ClusterViewSet`; added `DiscoveryViewSet` for beacon endpoint |
| `urls.py` | Added `/api/v1/discover/` route |
| `admin.py` | Node list: cluster name + heartbeat freshness badges; Cluster admin: inline member list + member count |
| `tests.py` | 13 new tests: cluster join/leave/members, master election, discovery beacon |

### Agent Changes (`platform/agent/`)

| File | Changes |
|---|---|
| `discovery/lan.py` | Full UDP broadcast implementation — sends JSON beacon to `255.255.255.255:42069`, listens for `discover_ack` responses |
| `main.py` | Discovery integration: if no `--master-url`, try UDP broadcast first; falls back to config |
| `config/agent.yaml` | Added `discovery_port: 42069`, `discovery_timeout: 3.0` |
| `config/settings.py` | Defaults for new discovery config keys |
| `tests/test_discovery.py` | 7 tests: manual URL, broadcast fallback, listener start/stop, discovery info |

## New API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/clusters/{id}/members/` | List cluster members with status, join time, master flag |
| `POST` | `/api/v1/clusters/{id}/join/` | Node joins a cluster |
| `POST` | `/api/v1/clusters/{id}/leave/` | Node leaves (clears master if was master) |
| `POST` | `/api/v1/clusters/{id}/elect-master/` | Designate a node as cluster master |
| `GET` | `/api/v1/clusters/{id}/` | Detail view — includes `member_count` + `member_summary` |
| `GET` | `/api/v1/discover/` | Beacon response — returns cluster master info for UDP |

## Discovery Flow

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

## Master Election

In v1, master election is **manual** — an operator or automated process calls `POST /api/v1/clusters/{id}/elect-master/` with a node ID. The designated node gets `is_designated_master=True` and is set as `Cluster.master_node`. A node that leaves the cluster automatically clears the master slot if it was the master.

## Cluster Model (Extended)

```
Cluster
├── id (UUID, PK)
├── name (unique)
├── master_node (FK → Node)
├── discovery_method (manual | udp)
├── discovery_port (default: 42069)
├── created_at
└── updated_at

Node (extended)
├── cluster (FK → Cluster, nullable)
├── joined_at (DateTime, nullable)
└── is_designated_master (bool, default: False)
```

## Test Results

```
Backend: 46 tests (24 nodes + 14 orchestration + 8 security)
Agent:   35 tests (14 state machine + 6 registration + 8 scheduler + 7 discovery)
```

### New Backend Tests

| Test | What It Validates |
|---|---|
| `test_list_clusters` | Cluster listing works |
| `test_create_cluster` | Cluster creation works |
| `test_cluster_detail_includes_members` | Detail view includes member_count |
| `test_join_cluster` | Node can join a cluster |
| `test_join_nonexistent_node` | Invalid node returns 400 |
| `test_leave_cluster` | Node can leave a cluster |
| `test_leave_clears_master` | Leaving clears master if was master |
| `test_members_list` | Member list shows all members |
| `test_elect_master` | Master election works for cluster members |
| `test_elect_master_node_not_in_cluster` | Outside node can't be elected |
| `test_discover_empty` | No masters → empty server list |
| `test_discover_with_master` | Cluster with master appears in discovery |
| `test_cluster_default_discovery_port` | Default port is 42069 |

### New Agent Tests

| Test | What It Validates |
|---|---|
| `test_manual_url` | Using configured master URL directly |
| `test_broadcast_fallback` | UDP broadcast → falls back to manual |
| `test_listener_start_stop` | UDP listener lifecycle |
| `test_discovery_info` | Discovery data structure correctness |

### Acceptance Criteria

| Criterion | Status | How |
|---|---|---|
| A device can find peers on the network | ✅ | UDP broadcast discovery or manual URL |
| A device can join a cluster | ✅ | `POST /clusters/{id}/join/` |
| The cluster can identify one active master | ✅ | `Cluster.master_node` FK + `elect-master/` endpoint |
| Member nodes can be listed from the dashboard | ✅ | Admin inline members + `/members/` API |

## Test Coverage Summary

### Backend Tests
- **Cluster CRUD**: create, list, detail with member count
- **Join/leave**: valid join, nonexistent node, leave clears master
- **Master election**: happy path, node-not-in-cluster rejection
- **Discovery beacon**: empty state, cluster-with-master state

### Agent Tests
- **Discovery modes**: manual URL, UDP broadcast, broadcast→fallback
- **UDP listener**: start/stop lifecycle, message handling
- **Discovery data**: response structure correctness

Run with:
```bash
# Backend
cd platform/master
python manage.py test nodes orchestration security

# Agent
cd platform/agent
python -m pytest tests/
```

## Key Decisions

| Decision | Rationale |
|---|---|
| **Manual master election** (v1) | Avoids consensus protocol complexity until the basic system is proven |
| **UDP broadcast on 255.255.255.255:42069** | Standard LAN broadcast address; 42069 is distinctive and unlikely to conflict |
| **JSON-over-UDP** | Simple, debuggable, no protocol parsing needed |
| **Fallback chain: broadcast → config → error** | Agent tries easiest path first, degrades gracefully |
| **Cluster membership via FK** | Simple relational model; no separate membership table needed |

## Post-Release Fixes

| # | Fix | File | Description |
|---|---|---|---|
| 1 | `token_path` type coercion | `agent_core/registration.py` | `os.path.join()` returns `str` but code expected `pathlib.Path` — wrapped in `Path()` constructor |
| 2 | Empty `device_id` in YAML | `config/settings.py` | `agent.yaml` has `device_id: ""` which overrode computed hostname default — strip empty values before `setdefault()` |

## Next

Added task orchestration in **Phase 4 — Task Model & Basic Orchestration**.
