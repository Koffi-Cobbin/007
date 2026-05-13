# Installation & Packaging Guide

> **Last updated:** 2026-05-13  
> **Covers:** PyInstaller executable, Windows service, deployment to target machines

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Build the Agent Executable](#2-build-the-agent-executable)
3. [Deploy the Master](#3-deploy-the-master)
4. [Deploy the Agent](#4-deploy-the-agent)
5. [Windows Service Installation](#5-windows-service-installation)
6. [Two-Laptop Deployment](#6-two-laptop-deployment)
7. [Distribution Options](#7-distribution-options)
8. [CI/CD Pipeline](#8-cicd-pipeline)
9. [Troubleshooting](#9-troubleshooting)
10. [Appendix: File Reference](#10-appendix-file-reference)

---

## 1. Architecture Overview

```
                    MASTER NODE (Django)
              ┌──────────────────────────────────┐
              │  Port 8000 — REST API            │
              │  Port 42069 — UDP Discovery      │
              │  PostgreSQL / SQLite Database     │
              │  django-q2 Task Queue             │
              └──────────┬───────────────────────┘
                         │ LAN (HTTP)
              ┌──────────▼───────────────────────┐
              │        AGENT POOL                │
              │  ┌──────────┐  ┌──────────┐      │
              │  │ Laptop A │  │ Laptop B │      │
              │  │ (agent)  │  │ (agent)  │      │
              │  └──────────┘  └──────────┘      │
              └──────────────────────────────────┘
```

### Components

| Component | Technology | Distribution Method |
|---|---|---|
| **Master (Django backend)** | Python + Django | Source code (`git clone` + `pip install`) |
| **Agent** | Python → PyInstaller `.exe` | Standalone executable (no Python needed) |
| **Database** | SQLite (dev) / PostgreSQL (prod) | Built-in / Docker |
| **Service manager** | NSSM (auto-downloaded) | Bundled at install time |

---

## 2. Build the Agent Executable

### Prerequisites

```powershell
# On your build machine (any Windows PC):
pip install pyinstaller
```

### Quick Build

```powershell
cd platform\agent
build_exe.bat
```

Output: `platform\agent\dist\dtask-agent\dtask-agent.exe` (~5 MB)

### Single-File Build

```powershell
build_exe.bat --onefile
```

Output: `platform\agent\dist\dtask-agent.exe` (~12 MB, self-contained)

### What's Inside the .exe

The executable bundles everything the agent needs at runtime:

| Bundled Item | Source | Purpose |
|---|---|---|
| Agent core | `agent_core/` | Registration, state machine, scheduler |
| Transport | `transport/` | HTTP client |
| Executor | `executor/` | Task runner + 6 built-in handler plugins |
| Plugin loader | `executor/loader.py` | Auto-discovers handlers at startup |
| Config | `config/agent.yaml` | Default configuration |
| Python runtime | CPython 3.13 | Interpreter + standard library |
| Dependencies | `requests`, `pyyaml`, `psutil` | HTTP, YAML parsing, system monitoring |

### Build Options

| Flag | Output | Use Case |
|---|---|---|
| *(none)* | `dist\dtask-agent\dtask-agent.exe` + support files | Development, quick iteration |
| `--onefile` | `dist\dtask-agent.exe` (single file) | Distribution to target machines |
| `--debug` | Verbose build log | Troubleshooting missing modules |

### Verifying the Build

```powershell
# Check the executable runs
dist\dtask-agent\dtask-agent.exe --help

# Expected output includes:
#   --master-url       Backend URL
#   --enrollment-key   Pre-shared enrollment key
#   --install-service  Install as Windows service
#   --uninstall-service  Remove the service
#   --service-status   Check service status

# Test it can discover built-in plugins (no master needed):
dist\dtask-agent\dtask-agent.exe --service-status
# Expected: "DTask Agent service status: not_installed"
```

---

## 3. Deploy the Master

### Development (SQLite — Zero Config)

```powershell
# On the machine that will be the master:
git clone <repo> 007
cd 007\platform\master
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

### Production (PostgreSQL — Recommended)

```yaml
# docker-compose.yml (create this in platform/master/)
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: dtask
      POSTGRES_PASSWORD: ${DTASK_DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready"]
      interval: 5s

  master:
    build: .
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgres://postgres:${DTASK_DB_PASSWORD}@postgres/dtask
      DJANGO_SECRET_KEY: ${DJANGO_SECRET_KEY}
    depends_on:
      postgres:
        condition: service_healthy
    command: >
      sh -c "python manage.py migrate &&
             python manage.py runserver 0.0.0.0:8000"
```

Or use a `Dockerfile`:

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]
```

### Firewall Configuration

```powershell
# Run as Administrator on the master machine:
New-NetFirewallRule -DisplayName "DTask Master 8000" `
  -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow

# Optional — for LAN discovery:
New-NetFirewallRule -DisplayName "DTask Discovery 42069" `
  -Direction Inbound -Protocol UDP -LocalPort 42069 -Action Allow
```

### Health Checks

The master provides two unauthenticated endpoints for load balancers:

```powershell
# Liveness — is the process alive?
curl http://localhost:8000/health/
# → {"status": "alive", "uptime_seconds": 1234, "version": "1.0.0"}

# Readiness — is it ready to serve traffic?
curl http://localhost:8000/ready/
# → {"status": "ready", "database": {"ok": true}}
```

---

## 4. Deploy the Agent

### Option A: Interactive (Foreground)

```powershell
# Run directly — good for testing, shows logs in real-time
.\dtask-agent.exe --enrollment-key demo-key --master-url http://192.168.1.100:8000
```

Press `Ctrl+C` to stop.

### Option B: Windows Service (Background)

```powershell
# Install once — runs on boot, auto-restarts on crash
.\dtask-agent.exe --install-service `
  --enrollment-key demo-key `
  --master-url http://192.168.1.100:8000 `
  --device-id my-laptop
```

The service:
- Starts automatically when Windows boots
- Runs in the background (no terminal window needed)
- Auto-restarts if the process crashes
- Logs output to `service_logs\stdout.log` and `service_logs\stderr.log`

### Option C: With Fallback Master (High Availability)

```powershell
.\dtask-agent.exe --install-service `
  --enrollment-key demo-key `
  --master-url http://master-a.internal:8000 `
  --fallback-url http://master-b.internal:8000 `
  --device-id my-laptop
```

If the primary master goes down, the agent automatically switches to the fallback.

### All CLI Options

```
--config CONFIG           Path to YAML config file (default: auto-search)
--master-url URL          Backend master URL (required)
--fallback-url URL        Optional fallback master for failover
--device-id ID            Unique identifier (defaults to hostname)
--enrollment-key KEY      Pre-shared enrollment key
--log-level LEVEL         DEBUG | INFO | WARNING | ERROR
--discovery-port PORT     UDP port for LAN discovery (default: 42069)
--discovery-timeout SEC   Seconds to wait for discovery (default: 3.0)
--install-service         Install as a Windows background service
--uninstall-service       Remove the Windows service
--service-status          Check service installation status
```

---

## 5. Windows Service Installation

### How It Works

The `--install-service` flag uses **NSSM** (Non-Sucking Service Manager) under the hood:

1. Downloads NSSM from `nssm.cc` (if not already present)
2. Extracts it to `tools\nssm-2.24\win64\nssm.exe`
3. Registers the agent as a Windows service named `DTaskAgent`
4. Configures the service to:
   - Start automatically on boot
   - Restart on crash (unlimited retries)
   - Log stdout to `service_logs\stdout.log`
   - Log stderr to `service_logs\stderr.log`
5. Starts the service immediately

### Service Commands

```powershell
# Install
.\dtask-agent.exe --install-service --master-url URL --enrollment-key KEY

# Check status
.\dtask-agent.exe --service-status
# → "DTask Agent service status: running"

# View logs (PowerShell)
Get-Content "$(Get-Item .).FullName\service_logs\stdout.log" -Tail 20
Get-Content "$(Get-Item .).FullName\service_logs\stderr.log" -Tail 20

# Start/Stop/Restart via native Windows commands (requires admin)
net start DTaskAgent
net stop DTaskAgent

# Uninstall
.\dtask-agent.exe --uninstall-service
```

### Service Architecture

```
Windows Service Manager (SCM)
        │
        ▼
  nssm.exe (service wrapper)
        │
        ├── manages process lifecycle
        ├── captures stdout/stderr → service_logs\
        └── auto-restarts on crash
        │
        ▼
  dtask-agent.exe (Python process)
        │
        ├── heartbeat loop (every 30s)
        ├── task polling loop (every 5s)
        └── plugin handlers (checksum, etc.)
```

---

## 6. Two-Laptop Deployment

### Quick Start

```
LAPTOP A (master + agent)              LAPTOP B (agent only)
  IP: 192.168.1.100                     IP: 192.168.1.101
  ┌──────────────────────┐              ┌──────────────────────┐
  │  Django runserver    │◄────HTTP────│  dtask-agent.exe     │
  │  Port 8000           │              │  --master-url        │
  │                      │              │  http://192.168.1.100│
  │  dtask-agent.exe     │              │  :8000               │
  │  (also runs here)    │              └──────────────────────┘
  └──────────────────────┘
```

### Step-by-Step

**Laptop A — Master:**

```powershell
# 1. Get the code
git clone <repo> 007

# 2. Install backend dependencies
cd 007\platform\master
pip install -r requirements.txt

# 3. Set up database
python manage.py migrate

# 4. Allow inbound connections
New-NetFirewallRule -DisplayName "DTask 8000" `
  -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow

# 5. Start the master (leave this terminal running)
python manage.py runserver 0.0.0.0:8000
```

**Laptop A — Create enrollment key:**

```powershell
# Open a second terminal
cd 007\platform\master
python manage.py shell -c "
from security.models import EnrollmentKey
EnrollmentKey.objects.create(key='my-key', is_active=True)
from nodes.models import Cluster
Cluster.objects.create(name='home-lab')
print('Ready')
"
```

**Laptop A — Start the local agent:**

```powershell
# Third terminal
cd 007\platform\agent\dist\dtask-agent
.\dtask-agent.exe --enrollment-key my-key --master-url http://localhost:8000
```

**Laptop B — Run the agent (no source code needed):**

```powershell
# 1. Copy the dist\dtask-agent folder from Laptop A (USB / network share)

# 2. Verify connectivity to Laptop A
ping 192.168.1.100
curl http://192.168.1.100:8000/health/

# 3. Run the agent
.\dtask-agent.exe --enrollment-key my-key --master-url http://192.168.1.100:8000

# Or install as a service to run permanently:
.\dtask-agent.exe --install-service `
  --enrollment-key my-key `
  --master-url http://192.168.1.100:8000
```

### Verify

```powershell
# From either laptop, check both nodes are connected:
curl http://192.168.1.100:8000/api/v1/nodes/
# → Should list both laptops

# Submit a test job:
curl -X POST http://192.168.1.100:8000/api/v1/jobs/ `
  -H "Content-Type: application/json" `
  -u admin:password `
  -d '{"task_type": "numerical", "input_payload": {"operation": "sum", "iterations": 100000, "total_chunks": 4}}'
```

---

## 7. Distribution Options

### Tier 1: ZIP Archive (Manual)

```powershell
# Build the .exe
cd platform\agent
build_exe.bat --onefile

# Package for distribution
Compress-Archive -Path dist\dtask-agent.exe -DestinationPath dtask-agent-v1.0.0.zip
```

Share the `.zip` file. Users extract and run — **no Python installation required.**

### Tier 2: Inno Setup Installer (Professional)

Create a `setup.iss` file for Inno Setup to produce a `Setup.exe`:

```pascal
; setup.iss
[Setup]
AppName=DTask Agent
AppVersion=1.0.0
DefaultDirName={pf}\DTaskAgent
DefaultGroupName=DTask Agent
OutputDir=.\installer
OutputBaseFilename=dtask-agent-setup

[Files]
Source: "dist\dtask-agent\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\DTask Agent (console)"; Filename: "{app}\dtask-agent.exe"

[Run]
Filename: "{app}\dtask-agent.exe"; Parameters: "--install-service"; Flags: runhidden
```

### Tier 3: pip Package (Python Users)

```toml
# pyproject.toml (would go in platform/agent/)
[project]
name = "dtask-agent"
version = "1.0.0"
description = "Distributed Task Orchestration — Agent"
dependencies = [
    "requests>=2.28",
    "pyyaml>=6.0",
]
scripts = { dtask-agent = "main:main" }
```

```powershell
# Users would install with:
pip install dtask-agent
dtask-agent --enrollment-key KEY --master-url URL
```

---

## 8. CI/CD Pipeline

### GitHub Actions — Automated Build

```yaml
# .github/workflows/build.yml
name: Build Agent Executable

on:
  push:
    tags:
      - 'v*'  # Trigger on version tags
  workflow_dispatch:       # Manual trigger

jobs:
  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      
      - name: Install dependencies
        run: |
          pip install -r platform/agent/requirements.txt
          pip install pyinstaller
      
      - name: Build executable
        run: |
          cd platform/agent
          python -m PyInstaller --noconfirm --onefile --name dtask-agent `
            --hidden-import executor.handlers --collect-submodules executor main.py
      
      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: dtask-agent-windows-${{ github.ref_name }}
          path: platform/agent/dist/dtasks-agent.exe
      
      - name: Create Release
        uses: softprops/action-gh-release@v2
        with:
          files: platform/agent/dist/dtasks-agent.exe
```

### Release Workflow

```
1. Developer tags commit:  git tag v1.0.0
2. GitHub Actions runs:    Build Agent Executable
3. Artifact uploaded:      dtask-agent-v1.0.0.zip
4. GitHub Release created: Auto-attaches .exe to release page
5. Users download:         Latest release from GitHub
```

---

## 9. Troubleshooting

### Build Issues

| Symptom | Cause | Fix |
|---|---|---|
| `pyinstaller not found` | PyInstaller not installed | `pip install pyinstaller` |
| `ModuleNotFoundError: executor` | Wrong working directory | Run build from `platform\agent\` |
| `.exe crashes on startup` | Missing hidden import | Add `--hidden-import agent_core.service` |
| `NSSM extraction failed` | No internet on build machine | Download NSSM manually from nssm.cc |

### Deployment Issues

| Symptom | Cause | Fix |
|---|---|---|
| `Connection refused` on master | Firewall blocking port 8000 | `New-NetFirewallRule -LocalPort 8000 -Action Allow` |
| `401 Unauthorized` on registration | Enrollment key already used | Create a new one: `EnrollmentKey.objects.create(key='new', is_active=True)` |
| Agent can't find master | Wrong IP address | Check `ipconfig` on master; verify with `ping` |
| Service won't start | Wrong working directory | Service runs from its install directory; use absolute paths |
| `psutil` not reporting CPU | psutil not bundled | Optional — agent falls back to `load=0.0` |

### Service Management

```powershell
# Service is installed but not running
net start DTaskAgent

# Check service status
sc query DTaskAgent

# View service logs
Get-Content .\service_logs\stdout.log -Tail 50

# Force remove service if --uninstall-service fails
sc stop DTaskAgent
sc delete DTaskAgent
```

---

## 10. Appendix: File Reference

### Agent Build Chain

```
agent/
├── main.py                        # Entry point — CLI, service, agent loop
├── agent_core/
│   ├── state_machine.py           # Node state machine (offline→enrolling→active→...)
│   ├── registration.py            # Enrollment + token persistence
│   ├── scheduler.py               # Heartbeat + task polling loop
│   └── service.py                 # Windows service management (NSSM)
├── executor/
│   ├── runner.py                  # Task dispatcher (uses plugin registry)
│   ├── plugin_base.py             # BaseWorkloadHandler abstract class
│   ├── loader.py                  # Plugin discovery (filesystem + PyInstaller fallback)
│   └── handlers/                  # 6 built-in plugins
│       ├── checksum.py
│       ├── file_processing.py
│       ├── image_processing.py
│       ├── data_transform.py
│       ├── python_execution.py
│       └── numerical.py
├── transport/
│   └── http_client.py             # REST client with retry + auth
├── config/
│   └── agent.yaml                 # Default configuration
├── plugins/                       # Third-party plugins go here
│   └── examples/
│       └── hello_world.py         # Example plugin
├── build_exe.bat                  # PyInstaller build script
└── requirements.txt               # pip dependencies
```

### Master Components (for reference)

```
master/
├── health/                 # Health/readiness endpoints (GET /health/, /ready/)
├── nodes/                  # Device management + cluster membership
├── orchestration/          # Job/task lifecycle + scheduler + plugin registry
├── security/               # Auth, audit logs, enrollment keys
└── config/
    ├── settings.py         # Django settings + DRF + auth backend
    └── urls.py             # Route table
```

---

## Quick Reference Card

```powershell
# ── BUILD ─────────────────────────────────────────────────
cd platform\agent
pip install pyinstaller
build_exe.bat --onefile

# ── MASTER ────────────────────────────────────────────────
cd platform\master
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000

# Create enrollment key:
python manage.py shell -c "from security.models import EnrollmentKey; EnrollmentKey.objects.create(key='demo', is_active=True)"

# ── AGENT (interactive) ───────────────────────────────────
.\dist\dtask-agent.exe --enrollment-key demo --master-url http://192.168.1.100:8000

# ── AGENT (service) ──────────────────────────────────────
.\dist\dtask-agent.exe --install-service --enrollment-key demo --master-url http://192.168.1.100:8000

# ── VERIFY ────────────────────────────────────────────────
curl http://192.168.1.100:8000/health/
curl http://192.168.1.100:8000/api/v1/nodes/
```
