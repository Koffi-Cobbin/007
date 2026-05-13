# Verification Guide — End-to-End Testing Walkthrough

> How to manually verify the platform works at each phase.
> Run these after completing each phase to confirm everything is wired correctly.

---

## Phase 1 & 2 — Backend + Agent E2E

This verifies: registration, enrollment key validation, heartbeat, capability reporting, task assignment, and admin visibility.

### Prerequisites

- Python 3.8+
- `pip install -r platform/master/requirements.txt`
- `pip install -r platform/agent/requirements.txt`

---

### Step 1 — Start the backend

```bash
cd platform/master
python manage.py migrate
python manage.py runserver
```

Leave this running. The backend will be at `http://localhost:8000`.

---

### Step 2 — Create a superuser (for admin UI)

```bash
cd platform/master
python manage.py createsuperuser
# Follow prompts — email can be blank
```

---

### Step 3 — Create an enrollment key + a test job

```bash
cd platform/master
python manage.py shell
```

Paste the following into the shell:

```python
from security.models import EnrollmentKey
from orchestration.models import Job, Task

# Create enrollment key
EnrollmentKey.objects.create(key="test-key-123", is_active=True)

# Create a job with a task for the agent to pick up
job = Job.objects.create(
    task_type="checksum",
    status="active",
    input_payload={"files": ["test.iso"]},
)
Task.objects.create(
    job=job,
    task_type="checksum",
    status="pending",
    payload={"files": ["test.iso"], "algorithm": "sha256"},
)

print(f"Ready — key=test-key-123, job={job.id}")
exit()
```

---

### Step 4 — Start the agent

```bash
cd platform/agent
pip install -r requirements.txt
python main.py --enrollment-key test-key-123 --master-url http://localhost:8000
```

**Expected output (annotated):**

```
2026-05-12T21:19:49 [INFO] __main__: dtask-agent v1.0.0 starting
2026-05-12T21:19:49 [INFO] __main__: Config loaded from: config\agent.yaml
2026-05-12T21:19:49 [INFO] __main__: Master URL: http://localhost:8000
2026-05-12T21:19:49 [INFO] discovery.lan: Using configured master

2026-05-12T21:19:49 [INFO] agent_core.registration:
    Registering device_id='DESKTOP-...' with master at http://localhost:8000

2026-05-12T21:19:51 [INFO] agent_core.registration:
    Registered successfully — node_id=abc123...

2026-05-12T21:19:51 [INFO] agent_core.registration:
    Saved identity to agent_data\agent_token.json

2026-05-12T21:19:51 [INFO] __main__:
    Agent registered — node_id=abc123..., state=active

2026-05-12T21:19:51 [INFO] agent_core.scheduler:
    Starting scheduler (heartbeat=30s, poll=5s)

2026-05-12T21:19:51 [DEBUG] agent_core.scheduler:
    Heartbeat sent (status=active, load=0.12)

2026-05-12T21:19:51 [DEBUG] agent_core.scheduler:
    No tasks available                      ← executor is a stub in Phase 2

... every 5 seconds ...

2026-05-12T21:19:56 [INFO] agent_core.scheduler:
    Task received: t-uuid (type=checksum)   ← agent picked up the task!
```

---

### Step 5 — Verify in the admin UI

Open `http://localhost:8000/admin/` and log in with the superuser from Step 2.

#### Nodes → Nodes

| Column | What to look for |
|---|---|
| **Hostname** | Your machine's name (e.g. `DESKTOP-A1GO6VV`) |
| **Status** | `idle` (waiting) or `busy` (if a task was assigned) |
| **Last heartbeat** | Updating every ~30 seconds — confirms the heartbeat loop works |
| **Agent version** | `1.0.0` |

Click into the node record — you'll see `device_id`, `platform`, `ip_address`.

#### Nodes → Node capabilities

The agent reports its hardware during enrollment:

| Field | What it shows |
|---|---|
| **CPU cores** | e.g. `12` (logical cores detected via psutil) |
| **Memory MB** | e.g. `16068` (total RAM) |
| **OS family** | `windows` or `linux` |
| **Workload types** | Empty list (not yet configured in agent.yaml) |

#### Nodes → Node heartbeats

Every heartbeat is logged with:

| Field | What it shows |
|---|---|
| **Status** | `active`, `idle`, or `busy` |
| **Current load** | CPU load 0.0–1.0 |
| **Resources** | JSON with cpu_percent, memory_used_mb, disk_free_mb |
| **Uptime seconds** | How long the agent has been running |
| **Received at** | Timestamp the backend received the heartbeat |

#### Orchestration → Tasks

| Column | What to look for |
|---|---|
| **ID** | UUID of the task |
| **Job** | Link to the parent job |
| **Status** | `pending` → `assigned` → (Phase 4: `running` → `completed`) |
| **Task type** | `checksum` |
| **Assigned to** | Your node (after the agent polls) |
| **Retry count** | `0` |

#### Orchestration → Task assignments

Records which node got which task and when:

| Column | Value |
|---|---|
| **Task** | UUID of the assigned task |
| **Node** | Your node |
| **Assigned at** | Timestamp of assignment |

#### Security → Enrollment keys

| Column | What changed |
|---|---|
| **Key** | `test-key-123` |
| **Active** | Now `false` — marked inactive after use |
| **Used by** | Your node — linked to the node record |

---

### Step 6 — Check the REST API directly

```bash
# List all nodes
curl http://localhost:8000/api/v1/nodes/

# Filter by status
curl "http://localhost:8000/api/v1/nodes/?status=idle"

# Get a specific node (replace with actual UUID)
curl http://localhost:8000/api/v1/nodes/<node-uuid>/

# List all tasks
curl http://localhost:8000/api/v1/tasks/

# List all jobs
curl http://localhost:8000/api/v1/jobs/

# Check audit logs
curl http://localhost:8000/api/v1/audit-logs/

# List protocol versions
curl http://localhost:8000/api/v1/protocol-versions/
```

---

### Step 7 — Verify reconnection

1. **Stop the agent** (Ctrl+C) and restart it **without** `--enrollment-key`:
   ```bash
   python main.py --master-url http://localhost:8000
   ```
   It should load the stored token and go straight to `active` without re-registering.

2. **Stop the backend** for 10 seconds while the agent is running, then restart it. The agent's heartbeat will fail silently and recover once the backend is back.

3. **Submit a duplicate result** (simulates idempotency):
   ```bash
   cd platform/master
   python manage.py shell
   ```
   ```python
   from orchestration.models import Task
   t = Task.objects.first()
   from django.test import Client
   c = Client()
   # First submission
   resp1 = c.post(f"/api/v1/tasks/{t.id}/result/",
       {"status": "completed", "output": {}}, content_type="application/json")
   print("First:", resp1.status_code)  # 200
   # Second submission (same task)
   resp2 = c.post(f"/api/v1/tasks/{t.id}/result/",
       {"status": "completed", "output": {}}, content_type="application/json")
   print("Second:", resp2.status_code)  # 200 — idempotent
   ```

---

## Phase 5 — Scheduling Intelligence E2E

This verifies: priority queues, scheduling scoring, health threshold filtering, and resource-aware placement.

### Prerequisites

- 2+ terminal sessions for running multiple agent instances
- Backend running (see Phase 1 & 2 steps above)

---

### Step 1 — Create enrollment keys and a cluster

```bash
cd platform/master
python manage.py shell
```

```python
from security.models import EnrollmentKey
from nodes.models import Cluster

EnrollmentKey.objects.create(key="phase5-key", is_active=True)
cluster = Cluster.objects.create(name="phase5-cluster")
print(f"Cluster ID: {cluster.id}")
exit()
```

---

### Step 2 — Start two agents in separate terminals

**Terminal A (strong node):**
```bash
cd platform/agent
python main.py --enrollment-key phase5-key --master-url http://localhost:8000
```

**Terminal B (weak node)** — start a second agent with a different `device_id`:
```bash
cd platform/agent
python main.py --enrollment-key phase5-key --device-id weak-node --master-url http://localhost:8000
```

---

### Step 3 — Create a high-priority job

```bash
cd platform/master
python manage.py shell
```

```python
from orchestration.models import Job, Task

job = Job.objects.create(
    task_type="checksum",
    status="active",
    priority="high",
    input_payload={"files": ["priority-test.iso"]},
)
Task.objects.create(job=job, task_type="checksum", status="queued", payload={"files": ["priority-test.iso"]}, priority="high")

low_job = Job.objects.create(
    task_type="checksum",
    status="active",
    priority="low",
    input_payload={"files": ["low-pri-test.iso"]},
)
Task.objects.create(job=low_job, task_type="checksum", status="queued", payload={"files": ["low-pri-test.iso"]}, priority="low")

print(f"High-priority task created (job={job.id})")
print(f"Low-priority task created (job={low_job.id})")
exit()
```

---

### Step 4 — Verify priority ordering

Poll the assign endpoint with either agent:

```bash
curl "http://localhost:8000/api/v1/tasks/assign/?node_id=<agent-uuid>"
```

**Expected:** You should receive the `high` priority task first, even if it was created after the low priority task. The response includes:

```json
{
  "task_id": "uuid",
  "priority": "high",
  "scheduling_score": {
    "overall": 0.85,
    "breakdown": {
      "capability": 0.90,
      "resource": 0.72,
      "health": 0.95,
      "reliability": 0.50
    }
  }
}
```

---

### Step 5 — Verify stronger node preference

With both agents running and polling:

1. The agent with more CPU cores / lower load should receive tasks before the weaker one
2. Check the scheduling score in each agent's assign response
3. Check the Django logs for `Skipping task` messages when a significantly better node exists

---

### Step 6 — Verify health threshold

Simulate an unhealthy node by marking it degraded:

```bash
cd platform/master
python manage.py shell
```

```python
from nodes.models import Node
n = Node.objects.filter(device_id="weak-node").first()
if n:
    n.status = "degraded"
    n.save()
    print(f"Marked {n.device_id} as degraded")
exit()
```

**Expected:** The degraded node stops receiving task assignments until its status returns to `idle` or `active`.

---

## What's Not Testable Yet

| Feature | Ready in Phase | Why |
|---|---|---|
| **All 6 v1 workload types** | Phase 4 | ✅ Run checksum/file/image/transform/python/numerical tasks end-to-end |
| **Scheduling intelligence** | Phase 5 | ✅ Priority queues, scoring, health thresholds, resource-aware placement |
| **WebSocket live updates** | Phase 6 | `asgi.py` has empty route table — no WS consumers yet |
| **Token auth on endpoints** | Phase 6 | Tokens are issued but not validated |
| **Auth hardening** | Phase 6 | No encryption, no per-node certificate auth |

---

## Common Issues & Fixes

| Symptom | Likely Cause | Fix |
|---|---|---|
| `AttributeError: 'str' object has no attribute 'exists'` | `token_path` passed as string instead of `Path` | Update `registration.py`: `self.token_path = Path(token_path) if token_path else Path(...)` |
| `device_id: ''` → backend rejects | YAML has `device_id: ""` overriding hostname default | Strip empty YAML values before `setdefault()` in `config/settings.py` |
| `Registration rejected: {'device_id': ['This field may not be blank.']}` | Same as above | Run agent with `--device-id my-machine` or fix config |
| `401 Unauthorized` on heartbeat | Token expired or backend restarted | Agent auto-detects and will re-register (Phase 2) |
| `ConnectionError` | Backend not running | Start the Django dev server first |
| Enrollment key not found | Key was already used or doesn't exist | Create a fresh one in the admin or shell |
| Agent stays on `active` never `idle` | First heartbeat may not have been sent yet | Wait up to 30s for heartbeat interval |
