# Master Failover Strategy

> **Phase:** 8  
> **Status:** Draft — 2026-05-13  
> **Audience:** Operators deploying the platform in production

---

## 1. Current Architecture (Single Master)

```
┌─────────────────────────────────────────┐
│              MASTER NODE                │
│  ┌─────────┐  ┌──────────┐  ┌────────┐ │
│  │ Django  │  │ django-  │  │ SQLite │ │
│  │  REST   │  │   q2     │  │ / PG   │ │
│  │  API    │  │ (queue)  │  │ (data) │ │
│  └─────────┘  └──────────┘  └────────┘ │
│         ▲                              │
│         │ REST/WS                       │
│         ▼                              │
│  ┌──────────────────────────────────┐  │
│  │         AGENT POOL               │  │
│  │  ┌──────┐ ┌──────┐ ┌──────┐    │  │
│  │  │node A│ │node B│ │node C│ ...│  │
│  │  └──────┘ └──────┘ └──────┘    │  │
│  └──────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

**Single point of failure:** If the master node goes down:
- No new jobs can be submitted
- In-flight tasks remain in `assigned` state (orphaned)
- Agents get connection errors and sit idle
- No automatic recovery

## 2. Failure Scenarios

| Scenario | Impact | Recovery Without This Strategy |
|---|---|---|
| **Master process crash** (Django server dies) | 5-60s downtime | Restart process manually |
| **Master OS crash / reboot** | 2-10min downtime | Wait for reboot + manual restart |
| **Master hardware failure** | Hours–days | Restore from backup on new hardware |
| **Network partition** (master isolated) | Variable | Agents detect connection loss, go offline |
| **Database corruption** | Data loss risk | Restore from backup |

## 3. Proposed v2 Architecture (Warm Standby)

```
                      ┌──────────────────────────────┐
                      │      LOAD BALANCER / DNS      │
                      │   (round-robin or failover)   │
                      └────────┬──────────────┬───────┘
                               │              │
                      ┌────────▼─────┐  ┌─────▼────────┐
                      │  MASTER A   │  │  MASTER B    │
                      │  (active)   │  │  (standby)   │
                      │             │  │              │
                      │  Django     │  │  Django      │
                      │  API        │  │  API         │
                      └──────┬──────┘  └──────┬───────┘
                             │                │
                             └────────┬───────┘
                                      │
                             ┌────────▼───────┐
                             │  PostgreSQL    │
                             │  (primary)     │
                             │                │
                             │  streaming ────► PostgreSQL
                             │  replication   │  (standby, hot)
                             └────────────────┘
```

### Key Components

| Component | Role |
|---|---|
| **PostgreSQL Primary** | Source of truth — all writes go here |
| **PostgreSQL Standby** | Hot standby — accepts reads, replays WAL from primary |
| **Master A (Active)** | Runs Django + django-q2, serves all agent requests |
| **Master B (Standby)** | Runs Django (idle), connected to standby DB (read-only) |
| **Load Balancer** | Routes agent traffic to active master; health check on `GET /health/` |
| **Shared File System** | Optional — for file-based task artifacts |

### Failover Procedure

#### Automatic Failover (Goal)

1. Load balancer detects master A is unhealthy (`GET /health/` fails)
2. Load balancer routes traffic to master B
3. Master B detects it should become active:
   - Promotes standby DB to primary (`pg_ctl promote`)
   - Starts django-q2 cluster worker
   - Updates `Cluster.master_node` in the database
   - Begins accepting agent requests
4. Agents reconnect to the new master via the load balancer URL

#### Manual Failover (v1 Procedure)

```bash
# 1. On standby node, promote the database
pg_ctl promote -D /var/lib/postgresql/standby

# 2. Start django-q2 cluster
cd /opt/dtask/master
python manage.py qcluster &

# 3. Start Django server
python manage.py runserver 0.0.0.0:8000

# 4. Update cluster master record
python manage.py shell -c "
from nodes.models import Cluster, Node
# Mark the new master
master = Node.objects.get(device_id='standby-node')
cluster = Cluster.objects.first()
cluster.master_node = master
cluster.save()
master.is_designated_master = True
master.save()
"

# 5. Point load balancer or update agent configs to new master URL
```

## 4. Agent-Side Failover Support

### Configuration

```yaml
# agent.yaml (Phase 8)
master:
  url: "http://master-a.internal:8000"
  fallback_url: "http://master-b.internal:8000"   # NEW
  health_check_interval: 15                        # NEW — seconds
  failback_poll_interval: 60                       # NEW — seconds

discovery:
  enabled: true
  port: 42069
  timeout: 3.0
```

### Agent Failover Flow

```
Normal operation:
  Agent → master-a:8000 (all requests)
  
Master A fails:
  Agent detects connection errors (or health check fails)
  Agent transitions to DEGRADED state
  Agent switches to fallback URL: master-b:8000
  Agent re-registers with master B (receives new token)
  Agent resumes normal operation

Master A recovers:
  Agent periodially polls original URL (failback_poll_interval)
  If master A is healthy → switches back (optional, configurable)
  Agent re-registers with master A
```

## 5. Recovery After Failover

### Orphaned Task Recovery

When a master fails, tasks in `assigned` or `running` status may be orphaned:

```bash
# Run on the new master after failover
python manage.py detect_stale_nodes --max-age 60
```

This reassigns any tasks assigned to agents that haven't reported back recently.

### Agent Re-registration

Agents connecting to the new master must re-register because:
- Their bearer token was specific to the old master's `Node` record
- The `ip_address` and `last_heartbeat` timestamps need updating
- The `cluster.master_node` reference must be updated

The agent's `registration.py` already handles `401 Unauthorized` by triggering re-registration.

## 6. Limitations (v2 Scope)

| Limitation | Impact | Planned For |
|---|---|---|
| **No active-active** | Standby is idle until failover | Phase 9+ |
| **Manual DB promotion** | Requires operator SSH access | Phase 9 auto-promotion |
| **No task queue replication** | django-q2 tasks in memory are lost on failover | django-q2 with shared DB backend (already configured) |
| **No split-brain protection** | Both masters could accept writes if network splits | Lease-based fencing (Phase 9) |

## 7. Recommendation for v1

For v1 deployments, the simplest approach to multi-master readiness is:

1. **Use PostgreSQL** (not SQLite) — enables streaming replication
2. **Configure a standby PostgreSQL** — hot standby for read queries
3. **Run Django on two nodes** — only one active at a time
4. **Use a TCP load balancer** (HAProxy, nginx) — health checks + failover
5. **Run `detect_stale_nodes` via cron** — recover orphaned tasks
6. **Document the manual failover procedure** (Section 3 above)
