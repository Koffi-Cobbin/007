# VISION.md — Distributed Task Orchestration Platform

## Elevator Pitch

A distributed platform that turns a local network of laptops and desktops into a cooperative task-execution cluster. One node acts as master, accepting jobs that are automatically split into sub-tasks and assigned to capable slave nodes. Each slave executes its assigned work and reports results back. The master aggregates results, handles failures, and provides visibility into cluster health. The system is designed from day one for clear contracts, LAN-first operation, and eventual migration of performance-critical components to Go or Rust.

## Core Design Principles

1. **Start simple, design for growth** — The first version solves a narrow problem well while leaving room for future device types and workloads.
2. **Separate control plane from execution plane** — The master/orchestrator is not tightly coupled to task execution details.
3. **Make the device agent lightweight** — The agent is small, reliable, and easy to run on many machines.
4. **Use explicit contracts** — Task formats, device capability formats, and result formats are versioned and documented.
5. **Prefer local-network first** — The earliest system works on a LAN before attempting internet-wide distribution.
6. **Security is not optional** — Device identity, authentication, and encrypted transport are part of the foundation.
7. **Observability from day one** — Logs, heartbeats, task history, and node status exist from the start.
8. **Future migration must be possible** — The Python/Django version defines interfaces cleanly enough to allow later replacement of performance-critical parts with Go or Rust services.

## v1 Scope

### IN (v1)

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

### OUT (v2+)

| Feature | Reason for deferral |
|---|---|
| Multi-master / failover | Requires consensus protocol, election logic — overkill for v1 |
| WAN / cross-site distribution | Network complexity, NAT traversal, security model more complex |
| Containerized execution | Adds Docker/k8s dependency — subprocess is simpler for v1 |
| Go/Rust agent or engine | Language migration comes after the interface contracts are proven |
| AI inference workloads | Requires GPU scheduling, model distribution — deferred to later phases |
| Mobile / embedded nodes | Different power profile, connectivity assumptions |
| Internet-wide device enrollment | Needs CA-style PKI, public endpoint — deferred to Phase 6+ |

## Target User / Use Case for v1

A developer or small team with multiple machines on the same local network who needs to run:

- Batch data processing across machines
- Parallel checksum or hash verification of large file sets
- Distributed image processing (resize, format conversion, watermarking)
- Chunked numerical or data transformation workloads

The user installs the Django backend on one machine and the agent on each participating machine. Agents discover or are pointed to the master, register, and wait for work.

## This Platform Is NOT

- A replacement for Kubernetes, Nomad, or Mesos (those target datacenter-scale container orchestration)
- A distributed computing framework in the style of Spark or Dask (those are data-parallel computation engines)
- A message queue or stream-processing system (Kafka, RabbitMQ, NATS)
- An IoT or embedded-device platform in v1 (that comes later)

## Success Criteria

The project is successful when:

- Multiple desktop/laptop devices can join the system
- One node can act as master
- The master can discover peers on the network
- The master can assign sub-tasks
- Slave nodes can execute and report back
- Task status is visible
- The design remains clean enough to support future growth into edge, mobile, and embedded orchestration

## Related Documents

| Document | Purpose |
|---|---|
| `ARCHITECTURE.md` | System architecture, component boundaries, data flow |
| `PROTOCOL.md` | API contracts, state machines, payload schemas |
| `WORKLOADS.md` | v1 workload definitions and qualification criteria |
| `ROADMAP.md` | Phase breakdown with acceptance criteria |
| `diagrams/system-architecture.drawio` | Visual system architecture diagram |
