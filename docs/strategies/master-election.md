# Master Election Strategy

> **Phase:** 8  
> **Status:** Draft — 2026-05-13  
> **Audience:** Developers planning the automatic election implementation

---

## 1. Current State (v1 — Manual Election)

In v1, master election is entirely manual:

```bash
POST /api/v1/clusters/{id}/elect-master/
{"node_id": "<uuid>"}
```

An operator or external automation calls this endpoint to designate a node as master. The system:
1. Sets `Node.is_designated_master = True` on the elected node
2. Sets `Cluster.master_node` FK to point to the elected node
3. Clears previous master designation from other nodes

**Limitations:**
- Requires human intervention on master failure
- No automatic detection of master health
- No consensus — any operator can elect any node
- No tie-breaking for split clusters

## 2. Proposed v2 Election Algorithm

### Requirements

| Requirement | Priority |
|---|---|
| Automatic detection of master failure | Critical |
| Only one master at a time (no split-brain) | Critical |
| Election completes within 30s of failure detection | High |
| Prefer existing master (stability) | Medium |
| Deterministic tie-breaking | Medium |
| Opaque to agents (they just connect to a URL) | High |

### Algorithm: Lease-Based Election with Deterministic Fallback

```
Every N seconds, the current master:
  ─► Writes to `cluster_lease` table with TTL (30s)

Every N seconds, every node:
  ─► Checks `cluster_lease`
  ─► If lease is fresh  ➔  master is alive, do nothing
  ─► If lease is expired ➔  enter election

Election (simplified RAFT-like):
  1. Node increments `cluster_term` counter
  2. Node votes for itself
  3. Node broadcasts `vote_request` to all cluster members
  4. Each member votes for the first candidate they hear from
     (or the candidate with the highest term number)
  5. Candidate with majority (> N/2) votes becomes master
  6. New master writes lease, starts accepting tasks
```

### Simplification for v1.5: Deterministic Priority List

For a simpler approach that avoids full consensus protocol:

```
Each node has a `election_priority` (configurable, default 0-100).
Higher priority = more likely to become master.

On master failure detection:
  1. Each node waits (100 - priority) × 100ms before declaring
  2. First node to claim mastership writes to `cluster_lease`
  3. Other nodes see the lease and stand down

Tie-breaker: lowest UUID wins (deterministic).
```

## 3. Database Schema for Election

```sql
-- Extension to existing Cluster model (or new model)
CREATE TABLE cluster_lease (
    cluster_id    UUID REFERENCES cluster(id),
    master_node_id UUID REFERENCES node(id),
    term          INTEGER NOT NULL DEFAULT 0,
    acquired_at   TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at    TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (cluster_id)
);

ALTER TABLE node ADD COLUMN election_priority INTEGER DEFAULT 50;
```

## 4. Manual Election API (v1 — Already Implemented)

```json
POST /api/v1/clusters/{id}/elect-master/
{"node_id": "<uuid>"}

Response 200:
{
  "cluster_id": "uuid",
  "master_node_id": "uuid",
  "status": "elected"
}
```

This endpoint is already fully implemented in Phase 3. Any operator automation tool can call it.

## 5. Integration with Cluster Membership

Master election is tightly coupled with cluster membership (Phase 3):

```
Node joins cluster   →   Can it become master?   →   Check election priority
                    │                           ├── Yes → elect
                    │                           └── No  → wait for current master
                    ▼
Node leaves cluster →   If it was master         →   Clear master slot
                    │   (already implemented:     →   Elect next in priority
                    │    leave/ endpoints
                    │    clear master)
                    ▼
Master heartbeats   →   If master stops          →   Detect via lease expiry
                    │   heartbeating              →   Run election
                    ▼
Network partition   →   Split cluster            →   Each partition elects
                                                        its own master
                                                        (split-brain risk →
                                                        see state-replication.md)
```

## 6. Priority Configuration (v1.5)

```yaml
# agent.yaml — multi-master configuration
master:
  url: "http://master-a.internal:8000"
  fallback_url: "http://master-b.internal:8000"
  
election:
  priority: 80                    # 0-100, higher = more likely to be master
  enabled: false                  # v1: manual only
  lease_ttl_seconds: 30
  vote_timeout_seconds: 15
```

```python
# settings.py — backend election configuration
ELECTION = {
    "LEASE_TTL_SECONDS": 30,
    "AUTO_ELECTION_ENABLED": os.environ.get("DTASK_AUTO_ELECTION", "False").lower() == "true",
    "MIN_VOTES": 2,
}
```

## 7. Recommendation for v1

| Feature | Recommendation | Phase |
|---|---|---|
| **Manual election** | ✅ Implemented (Phase 3) | v1 |
| **Priority-based auto-election** | Design complete, implement in v1.5 | v1.5 |
| **Full RAFT consensus** | Overkill for current scale — defer | Phase 9 |
| **Lease-based fencing** | Implement after auto-election | v2 |
| **Cluster term tracking** | Add when auto-election is implemented | v1.5 |

For v1 deployments:
- Use the existing manual election API
- Automate it via an external script / cron job
- Combine with `detect_stale_nodes` for task recovery
- The agent's `--fallback-master-url` provides basic failover without election
