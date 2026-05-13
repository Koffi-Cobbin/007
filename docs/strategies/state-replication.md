# State Replication Plan

> **Phase:** 8  
> **Status:** Draft — 2026-05-13  
> **Audience:** Infrastructure engineers deploying the platform

---

## 1. What State Exists

| State Type | Storage | Criticality | Recovery Method |
|---|---|---|---|
| **Node records** | PostgreSQL / SQLite | High | Database replication |
| **Job + Task records** | PostgreSQL / SQLite | High | Database replication |
| **Task queue messages** | django-q2 (ORM-backed) | Medium | Re-queued by `detect_stale_nodes` |
| **Enrollment keys** | PostgreSQL / SQLite | Low | Re-create via admin |
| **Audit logs** | PostgreSQL / SQLite | Low | Database replication |
| **Task artifacts** (files) | Local filesystem | Low | Re-run tasks |
| **Agent tokens** | PostgreSQL / SQLite + agent disk | Medium | Re-register on 401 |

## 2. Database Replication

### Recommended: PostgreSQL Streaming Replication

```
┌──────────────┐          ┌──────────────────┐
│  PRIMARY     │  WAL     │  STANDBY (hot)   │
│  PostgreSQL  │ ────────►│  PostgreSQL      │
│  (accepts    │  stream  │  (read-only,     │
│   writes)    │          │   replaying WAL) │
└──────────────┘          └──────────────────┘
```

**Configuration:**

```ini
# primary/postgresql.conf
wal_level = replica
max_wal_senders = 3
wal_keep_size = 512MB
```

```ini
# standby/postgresql.conf
hot_standby = on
primary_conninfo = 'host=primary-host port=5432 user=replicator password=...'
```

**Why PostgreSQL streaming:**

| Requirement | How It's Met |
|---|---|
| Zero data loss on failover | Synchronous commit mode |
| Read-only queries during normal ops | Hot standby accepts SELECT |
| Fast promotion (< 30s) | `pg_ctl promote` |
| No special hardware needed | Standard PostgreSQL feature |

### Why NOT SQLite for Multi-Master

| Issue | Impact |
|---|---|
| No built-in replication | Must use filesystem sync |
| Single-writer only | Can't run two Django instances |
| No WAL shipping | No incremental replication |
| **Recommendation:** SQLite for development only. PostgreSQL for any deployment requiring HA. | |

## 3. Task Queue State (django-q2)

django-q2 is configured with the ORM broker (not Redis):

```python
Q_CLUSTER = {
    "name": "orchestrator",
    "orm": "default",          # Uses the same database
    "retry": 300,
    "timeout": 300,
    ...
}
```

**Implications for failover:**

| Scenario | Behavior |
|---|---|
| **Master crashes with tasks in queue** | Tasks stored in DB — visible to new master after failover |
| **Task is mid-execution on agent** | Agent finishes and submits result; result accepted by new master |
| **Task was just dequeued by q2 worker** | q2 marks it as "started" but not completed; may need manual retry |
| **Shared DB across masters** | **NOT recommended** — both q2 clusters would compete for the same tasks |

**Recommendation:** django-q2 should only run on the active master. The standby master starts its q2 cluster only after promoting.

## 4. Task Artifacts (Files)

Tasks may produce output files (processed images, transformed data, etc.):

| Approach | Pros | Cons |
|---|---|---|
| **Local storage** (current) | Simple, zero setup | Lost on master failure |
| **Network filesystem** (NFS) | Survives failover | Single point of failure, slow |
| **Object store** (S3/MinIO) | Durable, scalable | Requires external service |
| **Agent-local storage** | Survives master failure; results uploaded via API | Already works — results are JSON |

**Recommendation for v1:** Keep using JSON results stored in the database. Task artifacts are already captured in `TaskResult.output` and `TaskResult.metrics`. No file-system state is critical.

## 5. Split-Brain Prevention

Split-brain occurs when both masters accept writes simultaneously.

### Detection

```
Heartbeat check:
  Master A writes to `cluster_master_heartbeat` table every 5s
  Master B monitors this heartbeat
  If heartbeat stops for > 15s → Master B assumes Master A is dead

But if it's a network partition:
  Both masters think the other is dead
  Both start accepting writes → DATA DIVERGENCE
```

### Prevention Strategies

| Strategy | Complexity | Effectiveness |
|---|---|---|
| **Lease-based fencing** | High | Best — only one writer at a time |
| **PostgreSQL trigger-based fencing** | Medium | Good — standby refuses writes |
| **Manual operator intervention** | Low | Adequate for v1 — pager before promote |
| **Shared lock file on NFS** | Medium | Acceptable — `flock` on promote |

### Recommended v1 Approach

For v1, use manual failover with a **fence before promote** check:

```bash
#!/bin/bash
# promote-standby.sh — run on standby node

# 1. Verify primary is truly dead
if ping -c 2 -W 3 $PRIMARY_HOST > /dev/null 2>&1; then
    echo "ERROR: Primary is still reachable. Do not promote."
    exit 1
fi

# 2. Verify no other standby has been promoted
if psql -c "SELECT pg_is_in_recovery()" | grep -q "f"; then
    echo "ERROR: This instance is already accepting writes."
    exit 1
fi

# 3. Promote
pg_ctl promote -D /var/lib/postgresql/data

# 4. Start application services
systemctl start dtask-qcluster
systemctl start dtask-gunicorn
```

## 6. Replication Test Plan

| Test | Procedure | Expected Outcome |
|---|---|---|
| **Streaming active** | Write row on primary, query on standby | Row visible within 1s |
| **Standby read-only** | INSERT on standby | Error: cannot write to standby |
| **Promotion** | Stop primary, promote standby | Standby accepts writes in < 30s |
| **Failback** | Promote old primary as new standby | Streaming resumes in opposite direction |
| **Re-queue tasks** | After promotion, run `detect_stale_nodes` | Orphaned tasks re-queued |

## 7. django-q2 Configuration for HA

```python
Q_CLUSTER = {
    "name": "orchestrator",
    "orm": "default",
    "retry": 300,
    "timeout": 300,
    "max_attempts": 3,
    "ack_failures": True,
    "poll": 5,
    "catch_up": True,      # Re-queue unacknowledged tasks on start
}
```

Setting `catch_up: True` on the standby means when the q2 cluster starts after failover, it will re-queue any tasks that were in-flight on the old master.
