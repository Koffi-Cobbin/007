# Phase 0 — Product Definition & Architecture Lock

> **Completed:** 2026-05-12  
> **Type:** 🧠 Design only (no code)  
> **Effort:** S (1–2 weeks)  
> **Status:** ✅ Complete

---

## Goal

Define the platform clearly enough to avoid building the wrong system.

## Deliverables

| # | Deliverable | File |
|---|---|---|
| 1 | Elevator pitch, v1 scope (IN/OUT), success criteria | `docs/VISION.md` |
| 2 | System architecture, component boundaries, data flows, Django vs Agent rules | `docs/ARCHITECTURE.md` |
| 3 | All API endpoints, payload schemas, state machines | `docs/PROTOCOL.md` |
| 4 | 6 v1 workload types with schemas + deferred types | `docs/WORKLOADS.md` |
| 5 | 10-phase breakdown with effort sizing | `docs/ROADMAP.md` |
| 6 | Visual system architecture diagram | `docs/diagrams/system-architecture.drawio` |

## Key Decisions

| Decision | Choice |
|---|---|
| **v1 topology** | 1 master (Django) + N slaves (Python agents) |
| **Communication** | REST + WebSocket |
| **Execution model** | Subprocess (no containers) |
| **Discovery** | UDP broadcast + manual join |
| **Workloads** | 6 types: file, image, checksum, data transform, Python, numerical |
| **Database** | SQLite (dev) / PostgreSQL (prod) |
| **Task queue** | django-q2 (database-backed, no Redis needed) |
| **Migration path** | Defined interfaces → Go/Rust in Phase 9 |

## v1 Scope (IN)

| Feature | Detail |
|---|---|
| **Master topology** | Single master node (Django control plane) |
| **Slave nodes** | Multiple slave nodes, each running a Python agent |
| **Discovery** | LAN discovery (UDP broadcast) or manual join via enrollment key |
| **Task model** | Jobs split into sub-tasks, assigned to capable nodes |
| **Workload types** | 6 types: file processing, batch image processing, checksum/hash, data transformation, Python function execution, chunked numerical processing |
| **Communication** | REST for API calls, WebSocket for live updates |
| **Execution** | Subprocess-based worker execution on each agent |
| **Admin** | Django admin UI for cluster inspection |
| **Storage** | SQLite (development), PostgreSQL (production); django-q2 for task queue |

## v1 Scope (OUT — deferred to v2+)

| Feature | Reason |
|---|---|
| Multi-master / failover | Requires consensus protocol, election logic |
| WAN / cross-site distribution | Network complexity, NAT traversal |
| Containerized execution | Adds Docker/k8s dependency |
| Go/Rust agent or engine | Language migration after contracts proven |
| AI inference workloads | GPU scheduling, model distribution |
| Mobile / embedded nodes | Different power profile, connectivity |
| Internet-wide enrollment | Needs CA-style PKI, public endpoint |

## Core Design Principles

1. **Start simple, design for growth** — First version solves a narrow problem well
2. **Separate control plane from execution plane** — Master not tightly coupled to execution details
3. **Make the device agent lightweight** — Small, reliable, easy to run on many machines
4. **Use explicit contracts** — Task formats, capability formats, result formats versioned and documented
5. **Prefer local-network first** — LAN before attempting internet-wide distribution
6. **Security is not optional** — Device identity, authentication, encrypted transport are foundational
7. **Observability from day one** — Logs, heartbeats, task history, node status from the start
8. **Future migration must be possible** — Clean interfaces for later Go/Rust replacement

## Success Criteria

- [x] Multiple desktop/laptop devices can join the system
- [x] One node can act as master
- [x] The master can discover peers on the network
- [x] The master can assign sub-tasks
- [x] Slave nodes can execute and report back
- [x] Task status is visible
- [x] Design remains clean enough for future growth

## Retrospective Notes

- Phase 0 was pure design — no code, which kept it focused and fast.
- The v1 scope table (IN vs OUT) has been useful for rejecting scope creep during later phase design discussions.
- django-q2 over Redis simplifies the development setup significantly (no external services needed to run the backend).
- SQLite as default means zero-config onboarding for new developers.

## Test Results

No tests — pure design phase. Validation was through team review and document walkthroughs.

## Next

Built the foundation in **Phase 1 — Foundation Backend & Data Model**.
