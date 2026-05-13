# Deploying on Two Windows Laptops

A step-by-step guide to running the distributed task platform across two Windows machines on the same LAN.

---

## Overview

```
Laptop A (192.168.1.100)          Laptop B (192.168.1.101)
  ┌──────────────────────┐          ┌──────────────────────┐
  │  Django Master       │          │  Agent only          │
  │  (port 8000)         │◄────────►│                      │
  │                      │  REST    │  python main.py      │
  │  Agent also runs     │          │  --master-url        │
  │  on this machine     │          │  http://192.168.1.100│
  └──────────────────────┘          └──────────────────────┘
```

**Laptop A** runs everything: the Django master + one agent.  
**Laptop B** runs just the agent, connecting to Laptop A's master.

Both must be on the same local network.

---

## Prerequisites (Both Laptops)

### 1. Install Python

Download Python 3.10 or later from [python.org](https://python.org).  

**During installation, check "Add Python to PATH".** Verify:

```powershell
python --version
```

### 2. Get the Code

Copy the project folder to both laptops (USB drive, network share, or git clone):

```powershell
# Option A: USB / network share — copy the entire `007` folder
# Option B: git clone (if you have a repo)
git clone <your-repo-url> 007
```

### 3. Install Dependencies

Open PowerShell on **both** laptops and run:

```powershell
# Backend dependencies (Laptop A only)
cd C:\path\to\007\platform\master
pip install -r requirements.txt

# Agent dependencies (both laptops)
cd C:\path\to\007\platform\agent
pip install -r requirements.txt

# Optional — better resource reporting:
pip install psutil
```

---

## Laptop A — Set Up the Master

### Step 1 — Find your IP address

```powershell
ipconfig
# Look for:  IPv4 Address. . . . . . . . . . . : 192.168.1.100
```

Write down this IP — you'll need it for Laptop B.

### Step 2 — Allow inbound connections on port 8000

```powershell
# Run as Administrator:
New-NetFirewallRule -DisplayName "DTask Master 8000" `
  -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

If you want to use LAN discovery (UDP broadcast), also allow port 42069:

```powershell
New-NetFirewallRule -DisplayName "DTask Discovery 42069" `
  -Direction Inbound -Protocol UDP -LocalPort 42069 -Action Allow
```

### Step 3 — Start the backend

Open **PowerShell Terminal 1**:

```powershell
cd C:\path\to\007\platform\master
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

`0.0.0.0:8000` tells Django to listen on all network interfaces (not just localhost). Leave this terminal running.

### Step 4 — Create an enrollment key

Open **PowerShell Terminal 2**:

```powershell
cd C:\path\to\007\platform\master
python manage.py shell -c "
from security.models import EnrollmentKey;
EnrollmentKey.objects.create(key='demo-key', is_active=True)
print('Key created: demo-key')
"
```

### Step 5 — (Optional) Create a cluster

```powershell
python manage.py shell -c "
from nodes.models import Cluster;
Cluster.objects.create(name='home-lab')
print('Cluster created')
"
```

---

## Laptop A — Start the Agent

Open **PowerShell Terminal 3**:

```powershell
cd C:\path\to\007\platform\agent
python main.py --enrollment-key demo-key --master-url http://localhost:8000 --device-id laptop-a-agent
```

You should see:

```
Registered successfully — node_id=abc123...
Starting scheduler (heartbeat=30s, poll=5s)
```

---

## Laptop B — Join the Cluster

### Step 1 — Allow outbound connections

Windows usually allows outbound by default. No firewall changes needed on Laptop B unless you have a strict policy.

### Step 2 — Test connectivity to Laptop A

```powershell
# Replace with Laptop A's actual IP
ping 192.168.1.100
# Verify port 8000 is reachable:
curl http://192.168.1.100:8000/health/
```

Expected response: `{"status": "alive", "uptime_seconds": ..., "version": "1.0.0"}`

### Step 3 — Start the agent

```powershell
cd C:\path\to\007\platform\agent
python main.py --enrollment-key demo-key --master-url http://192.168.1.100:8000 --device-id laptop-b-agent
```

You should see:

```
Registered successfully — node_id=xyz789...
Starting scheduler (heartbeat=30s, poll=5s)
No tasks available
```

The "No tasks available" message is normal — there's no work yet.

---

## Verify It's Working

### Check connected nodes

On **either** laptop, open a browser or PowerShell:

```powershell
curl http://192.168.1.100:8000/api/v1/nodes/
```

You should see **two nodes** listed — `laptop-a-agent` and `laptop-b-agent`.

### Submit a test job

On **Laptop A**, open a new PowerShell terminal:

```powershell
cd C:\path\to\007\platform\master
python manage.py shell
```

```python
from orchestration.models import Job, Task

# Create a checksum job with 3 files
job = Job.objects.create(
    task_type="checksum",
    status="active",
    input_payload={
        "files": ["C:\\Windows\\notepad.exe",
                   "C:\\Windows\\write.exe",
                   "C:\\Windows\\regedit.exe"],
        "algorithm": "sha256",
    },
)
# Manually create sub-tasks (avoids async queue setup)
for f in ["C:\\Windows\\notepad.exe",
          "C:\\Windows\\write.exe",
          "C:\\Windows\\regedit.exe"]:
    Task.objects.create(
        job=job,
        task_type="checksum",
        status="queued",
        payload={"files": [f], "algorithm": "sha256"},
    )
print(f"Job {job.id} created with 3 tasks")
exit()
```

### Watch the agents pick up tasks

**Laptop A agent logs** should show:

```
Task received: <uuid> (type=checksum)
Executing task type=checksum timeout=300s
```

**Laptop B agent logs** should also show tasks being received.

### Check progress

```powershell
curl http://192.168.1.100:8000/api/v1/jobs/<job-uuid>/progress/
```

The `progress_pct` increases as agents complete tasks.

---

## What If Something Doesn't Work?

### Symptom: Agent can't connect to master

```powershell
# On the agent machine, test connectivity:
curl http://192.168.1.100:8000/health/

# If this fails:
#   - Check the IP address is correct
#   - On Laptop A, verify `python manage.py runserver 0.0.0.0:8000` is running
#   - On Laptop A, check the firewall rule exists:
Get-NetFirewallRule -DisplayName "DTask Master 8000"
```

### Symptom: Registration fails with "401"

The enrollment key may be already used or mistyped. Create a fresh one:

```powershell
# On Laptop A:
cd C:\path\to\007\platform\master
python manage.py shell -c "
from security.models import EnrollmentKey;
EnrollmentKey.objects.create(key='fresh-key', is_active=True)
"
```

Then restart agents with `--enrollment-key fresh-key`.

### Symptom: Both agents run on the same laptop

If you're testing both agents on one machine (for development), they need different `--device-id` values:

```powershell
# Terminal A
python main.py --enrollment-key demo-key --master-url http://localhost:8000 --device-id agent-alpha

# Terminal B
python main.py --enrollment-key demo-key --master-url http://localhost:8000 --device-id agent-beta
```

### Symptom: Jobs stay "pending" and never get assigned

The job needs to have `status="active"` and the tasks need `status="queued"`. If you used `perform_create` (the API), it auto-splits. If you're using the shell, make sure statuses are set correctly:

```python
job = Job.objects.create(task_type="checksum", status="active", ...)
Task.objects.create(job=job, task_type="checksum", status="queued", ...)
```

Also make sure at least one agent has the matching workload type in its capabilities. Check via:

```python
from nodes.models import NodeCapability
for cap in NodeCapability.objects.all():
    print(cap.node.device_id, cap.workload_types)
```

---

## Creating a Real Job via the API

Once things are working, you can submit jobs via `curl` or a REST client:

```powershell
curl -X POST http://192.168.1.100:8000/api/v1/jobs/ `
  -H "Content-Type: application/json" `
  -u admin:password `
  -d '{
    "task_type": "numerical",
    "priority": "high",
    "input_payload": {
      "operation": "monte_carlo",
      "iterations": 1000000,
      "total_chunks": 6
    }
  }'
```

This creates a Monte Carlo π estimation job split into 6 chunks — distributed across both laptops by the scheduler.

---

## What's Happening Under the Hood

```
Laptop B agent polls:  GET /api/v1/tasks/assign/?node_id=<uuid>
                        ├── Backend finds eligible tasks
                        ├── Scheduler scores Laptop A vs Laptop B
                        ├── Assigns to the best node
                        └── Returns task with scheduling score

Agent executes:         sha256(C:\Windows\notepad.exe)
                        └── POST /api/v1/tasks/<id>/result/

Aggregation:            When all 3 tasks done
                        └── Job → COMPLETED
```

---

## Next Steps

Once you have two laptops working together, try:

1. **Priority jobs** — submit a `"priority": "high"` job and watch it get assigned before lower-priority tasks
2. **Custom plugin** — drop a `.py` handler in the `plugins/` folder on both laptops, register the type, submit jobs
3. **Stale node detection** — stop one agent, run `python manage.py detect_stale_nodes`, watch tasks get reassigned
4. **Dashboard** — browse `http://192.168.1.100:8000/admin/` to see nodes, tasks, audit logs
