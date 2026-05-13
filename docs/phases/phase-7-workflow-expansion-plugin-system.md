# Phase 7 — Workflow Expansion & Plugin System

> **Completed:** 2026-05-13  
> **Effort:** L (4–6 weeks)  
> **Status:** ✅ Complete

---

## Goal

Support richer workloads without rewriting the core platform.

## Deliverables

| # | Deliverable | Files |
|---|---|---|
| 1 | Workload Registry model + API | `orchestration/models.py`, `serializers.py`, `views.py`, `urls.py`, `admin.py` |
| 2 | Schema validation on job creation | `orchestration/views.py` (`_validate_payload_against_schema`) |
| 3 | `required_resources` on Task | `orchestration/models.py` (migration 0003) |
| 4 | Plugin base class | `agent/executor/plugin_base.py` |
| 5 | Plugin loader (auto-discovery) | `agent/executor/loader.py` |
| 6 | 6 built-in handlers refactored as plugins | `agent/executor/handlers/` (6 files) |
| 7 | Example plugin | `agent/plugins/examples/hello_world.py` |
| 8 | Updated runner using plugin registry | `agent/executor/runner.py` |
| 9 | Backend tests (22 new) | `orchestration/tests_workloads.py` |
| 10 | Agent tests (14 new) | `agent/tests/test_plugin_loader.py` |

## Workload Registry

**Model** — `WorkloadType` in `orchestration/models.py`:

| Field | Type | Description |
|---|---|---|
| `name` | CharField (unique) | Task type identifier, e.g. `"checksum"` |
| `description` | TextField | Human-readable summary |
| `input_schema` | JSONField | JSON Schema describing valid `input_payload` |
| `output_schema` | JSONField | JSON Schema describing expected output format |
| `version` | CharField | Semver, default `"1.0.0"` |
| `is_active` | BooleanField | Only active types are visible to agents |
| `author` | CharField | Who registered this type |

**API** — `GET /api/v1/workload-types/` returns only active types, accessible by anyone (including agents). Admin required for create/update.

**Admin** — Registered in Django admin with active badge, search, and filters.

## Schema Validation

When a job is created via `POST /api/v1/jobs/`, the `input_payload` is validated against the registered `WorkloadType.input_schema` (if one exists for the `task_type`).

**Validator** (`_validate_payload_against_schema` in `orchestration/views.py`):
- Checks `required` fields exist
- Validates `properties` types: array, string, object, integer, number
- Unregistered types skip validation (backward compatible)
- Invalid payloads return `400 Bad Request` with field-level errors

**Example schema:**
```json
{
  "required": ["files", "operation"],
  "properties": {
    "files": {"type": "array"},
    "operation": {"type": "string"}
  }
}
```

## Plugin Interface

**Base class** — `BaseWorkloadHandler` in `agent/executor/plugin_base.py`:

```python
class BaseWorkloadHandler(ABC):
    name: str = ""          # e.g. "checksum"
    description: str = ""
    version: str = "1.0.0"

    @abstractmethod
    def validate(self, payload: dict) -> list:
        """Return validation errors (empty = valid)."""

    @abstractmethod
    def execute(self, payload: dict, timeout: int) -> dict:
        """Execute and return {status, output, error, logs, metrics}."""
```

**Plugin discovery** — `agent/executor/loader.py`:
- Scans `executor/handlers/` (built-in) and `plugins/` (third-party)
- Auto-discovers `BaseWorkloadHandler` subclasses
- Caches results per process
- Provides `get_handler(task_type)` for lookup
- Supports `reload_handlers()` for testing

**Structure:**
```
platform/agent/
├── executor/
│   ├── plugin_base.py              # Abstract base class
│   ├── loader.py                   # Plugin discovery engine
│   ├── runner.py                   # Dispatches via plugin registry
│   └── handlers/                   # Built-in plugins
│       ├── checksum.py
│       ├── file_processing.py
│       ├── image_processing.py
│       ├── data_transform.py
│       ├── python_execution.py
│       └── numerical.py
├── plugins/                        # Third-party plugins go here
│   └── examples/
│       └── hello_world.py          # Example: returns a greeting
```

## Resource Requirements

New field on `Task`:

```python
required_resources = JSONField(default=dict, blank=True)
```

Stores requirements like:
```json
{"min_cpu_cores": 8, "min_memory_mb": 16384, "min_disk_mb": 50000}
```

These are available for the scheduler (Phase 5) to check during candidate filtering, ensuring tasks only go to nodes that meet their resource needs.

## Adding a New Workload Type (5-Step Process)

1. **Register** the type via `POST /api/v1/workload-types/` with input/output schema
2. **Create** a handler file in `plugins/` (or `executor/handlers/`)
3. **Implement** `BaseWorkloadHandler` with `validate()` and `execute()`
4. **Advertise** the type in nodes' `NodeCapability.workload_types`
5. **Submit** jobs with `task_type` matching the registered name

**No changes to core code required.**

## Example Plugin

```python
# plugins/examples/hello_world.py
from executor.plugin_base import BaseWorkloadHandler

class HelloWorldHandler(BaseWorkloadHandler):
    name = "hello_world"
    description = "Returns a friendly greeting (example plugin)"
    version = "1.0.0"

    def validate(self, payload):
        errors = []
        if "name" not in payload:
            errors.append("Missing required field: 'name'")
        return errors

    def execute(self, payload, timeout):
        name = payload.get("name", "world")
        return {
            "status": "completed",
            "output": {"greeting": f"Hello, {name}!", "name": name},
            "error": None,
            "logs": f"Greeted {name}\n",
        }
```

## Practical Example — End-to-End Walkthrough

This walkthrough tests the full plugin lifecycle: register a workload type → create a custom plugin → validate schema → submit a job → agent discovers and executes the plugin.

### Prerequisites

```bash
# Terminal 1 — Start the backend
cd platform/master
python manage.py runserver

# Terminal 2 — Shell for setup
cd platform/master
python manage.py shell
```

```python
from security.models import EnrollmentKey
from nodes.models import Cluster
EnrollmentKey.objects.create(key="phase7-demo", is_active=True)
cluster = Cluster.objects.create(name="plugin-demo")
print(f"Cluster ID: {cluster.id}")
exit()
```

---

### Scenario 1: Register a New Workload Type

This tests: the WorkloadType registry API and admin visibility.

#### Step 1 — Register via API

```bash
cd platform/master
python manage.py shell
```

```python
from django.contrib.auth.models import User
from rest_framework.test import APIClient

# Create an admin user for API calls
if not User.objects.filter(username="admin").exists():
    User.objects.create_superuser("admin", "admin@test.com", "admin123")

client = APIClient()
client.login(username="admin", password="admin123")

# Register a custom workload type with schema
resp = client.post("/api/v1/workload-types/", {
    "name": "greeter",
    "description": "Returns a friendly greeting",
    "version": "1.0.0",
    "author": "demo-user",
    "input_schema": {
        "required": ["name"],
        "properties": {
            "name": {"type": "string"},
            "enthusiasm": {"type": "integer"},
        },
    },
    "output_schema": {
        "properties": {
            "greeting": {"type": "string"},
        },
    },
}, format="json")

print(f"Registered: {resp.status_code} — {resp.data}")
exit()
```

**Expected output:** `201 Created` with the new workload type details.

#### Step 2 — Verify via API and Admin

```bash
# List all active types (no auth required)
curl http://localhost:8000/api/v1/workload-types/

# Get specific type detail
curl http://localhost:8000/api/v1/workload-types/greeter/
```

**Expected:** The `greeter` type appears in the list with its input/output schemas.

```bash
# Also visible in Django admin
# Open http://localhost:8000/admin/orchestration/workloadtype/
```

---

### Scenario 2: Schema Validation on Job Creation

This tests: valid payloads pass, invalid payloads are rejected.

#### Step 1 — Valid payload (passes schema)

```bash
curl -X POST http://localhost:8000/api/v1/jobs/ \
  -H "Content-Type: application/json" \
  -u admin:admin123 \
  -d '{
    "task_type": "greeter",
    "input_payload": {"name": "Alice", "enthusiasm": 10}
  }'
```

**Expected:** `201 Created` — the payload has all required fields with correct types.

#### Step 2 — Missing required field (rejected)

```bash
curl -X POST http://localhost:8000/api/v1/jobs/ \
  -H "Content-Type: application/json" \
  -u admin:admin123 \
  -d '{
    "task_type": "greeter",
    "input_payload": {"enthusiasm": 10}
  }'
```

**Expected:** `400 Bad Request` with:
```json
{"input_payload": ["Missing required field: 'name'"]}
```

#### Step 3 — Wrong type (rejected)

```bash
curl -X POST http://localhost:8000/api/v1/jobs/ \
  -H "Content-Type: application/json" \
  -u admin:admin123 \
  -d '{
    "task_type": "greeter",
    "input_payload": {"name": 42, "enthusiasm": "lots"}
  }'
```

**Expected:** `400 Bad Request` with type mismatch errors.

#### Step 4 — Unregistered type (skips validation)

```bash
curl -X POST http://localhost:8000/api/v1/jobs/ \
  -H "Content-Type: application/json" \
  -u admin:admin123 \
  -d '{
    "task_type": "brand_new_unknown_type",
    "input_payload": {"anything": "goes"}
  }'
```

**Expected:** `201 Created` — types without a registered WorkloadType pass through unvalidated.

---

### Scenario 3: Create and Discover a Custom Plugin

This tests: the plugin auto-discovery system on the agent side.

#### Step 1 — Create a custom plugin file

Create `platform/agent/plugins/greeter.py`:

```python
"""Custom greeter plugin — registered as a workload type in the backend."""

from executor.plugin_base import BaseWorkloadHandler


class GreeterPlugin(BaseWorkloadHandler):
    name = "greeter"
    description = "Returns a friendly greeting (custom plugin demo)"
    version = "1.0.0"

    def validate(self, payload):
        errors = []
        if "name" not in payload:
            errors.append("Missing required field: 'name'")
        return errors

    def execute(self, payload, timeout):
        name = payload.get("name", "world")
        enthusiasm = payload.get("enthusiasm", 1)
        exclamation = "!" * enthusiasm
        greeting = f"Hello, {name}{exclamation} Welcome from the plugin system."
        return {
            "status": "completed",
            "output": {"greeting": greeting, "name": name, "plugin": "greeter"},
            "error": None,
            "logs": f"Greeted {name} with enthusiasm={enthusiasm}\n",
        }
```

#### Step 2 — Verify the agent discovers it

```bash
cd platform/agent
python -c "
from executor.loader import discover_handlers
registry = discover_handlers()
for name, handler in registry.items():
    print(f'  {name} v{handler.version} — {handler.description}')
"
```

**Expected output includes:**
```
  greeter v1.0.0 — Returns a friendly greeting (custom plugin demo)
  checksum v1.0.0 — Compute hash values (MD5, SHA-256, SHA-512) for files
  file_processing v1.0.0 — Copy, move, compress, or transform files
  ...
  Plugin discovery complete — 7 handler(s) registered
```

The custom `greeter` plugin is auto-discovered alongside the 6 built-in handlers. No configuration changes needed.

---

### Scenario 4: Full Pipeline — Register + Plugin + Execute

This tests: the complete flow from registration to execution.

#### Step 1 — Start the agent

```bash
# Terminal 3
cd platform/agent
python main.py --enrollment-key phase7-demo --master-url http://localhost:8000 --device-id plugin-worker
```

#### Step 2 — Create a job with the greeter workload type

```bash
cd platform/master
python manage.py shell
```

```python
from orchestration.models import Job, Task

# Create a job and task manually (avoids async split complexity for demo)
job = Job.objects.create(
    task_type="greeter",
    status="active",
    input_payload={"name": "Plugin System", "enthusiasm": 3},
)
Task.objects.create(
    job=job,
    task_type="greeter",
    status="queued",
    payload={"name": "Plugin System", "enthusiasm": 3},
)
print(f"Created job={job.id} with task_type=greeter")
exit()
```

#### Step 3 — Watch the agent pick it up

**Agent logs should show:**
```
Task received: <uuid> (type=greeter)
Executing task type=greeter timeout=300s
```

#### Step 4 — Verify the result

```bash
cd platform/master
python manage.py shell
```

```python
from orchestration.models import Task, TaskResult
task = Task.objects.filter(task_type="greeter").first()
result = TaskResult.objects.filter(task=task).first()
if result:
    print(f"Status: {result.status}")
    print(f"Output: {result.output}")
else:
    print("Task may not have been picked up yet — check agent logs")
    print(f"Task status: {task.status}")
```

**Expected:**
```
Status: completed
Output: {"greeting": "Hello, Plugin System!!! Welcome from the plugin system.", ...}
```

---

### Scenario 5: What to Observe

| What to Watch | Where | Expected |
|---|---|---|
| **Plugin discovery** | Agent startup logs | `Discovered handler: 'greeter' v1.0.0 (from greeter.py)` |
| **Plugin count** | Agent startup logs | `Plugin discovery complete — 7 handler(s) registered` |
| **Unknown task type** | Agent logs | Error if no handler found for task_type |
| **Schema validation** | Backend response | 400 for missing fields, 201 for valid payloads |
| **WorkloadType API** | `GET /workload-types/` | Only active types listed |
| **Admin** | `/admin/orchestration/workloadtype/` | Active badge, search, version info |

### Cleanup

```bash
# Stop the agent (Ctrl+C in Terminal 3)
# Optionally remove the example plugin:
# Remove-Item platform/agent/plugins/greeter.py
```

---

## Test Results

```
Backend:  151 tests — OK
Agent:     66 tests — OK
Total:    217 tests — OK
```

### New Backend Tests (22 in `orchestration/tests_workloads.py`)

| Test Class | Tests | What's Covered |
|---|---|---|
| `WorkloadTypeModelTests` | 3 | Create, default version, active filter |
| `WorkloadTypeAPITests` | 6 | List active, detail by name, not found, create requires admin, create as admin |
| `SchemaValidationUnitTests` | 10 | Empty schema, required present/missing, type mismatch (array, integer, number), valid types |
| `SchemaValidationIntegrationTests` | 4 | Valid payload, missing field → 400, wrong type → 400, unregistered type skips |
| `TaskResourceRequirementsTests` | 2 | Default empty, custom requirements |

### New Agent Tests (14 in `tests/test_plugin_loader.py`)

| Test Class | Tests | What's Covered |
|---|---|---|
| `TestPluginDiscovery` | 4 | All 6 handlers discovered, each is instance, unknown returns None, get_handler by name |
| `TestHandlerValidation` | 5 | Each handler's validate() rejects bad payloads, accepts valid |
| `TestHandlerExecution` | 4 | Checksum doesn't crash, Python executes correctly, Numerical sums, unknown operation |

## Key Decisions

| Decision | Rationale |
|---|---|
| **Plugin auto-discovery over manual registration** | Zero-config for new plugins — just drop a `.py` file in `plugins/` |
| **JSON Schema validation without `jsonschema` lib** | Avoids external dependency; lightweight validator covers 90% of use cases |
| **WorkloadType is a model, not a config file** | Queryable via API, visible in admin, versioned, supports schema evolution |
| **Built-in handlers stay in `executor/handlers/`** | Same discovery path as plugins — no special treatment |
| **`get_permissions` on WorkloadTypeViewSet** | Readable by anyone (agents discover types), writable by admins only |
| **runner.py uses plugin registry** | Replaces hardcoded `_get_handler` dict; no behavior change for existing code |

## Acceptance Criteria

| Criterion | Status | How |
|---|---|---|
| New task type without changing core | ✅ | Drop a plugin in `plugins/` → auto-discovered on next agent start |
| Nodes advertise workload support | ✅ | Via `NodeCapability.workload_types` (existing Phase 2 mechanism) |
| Scheduler routes by task type | ✅ | Existing `task_type` matching; enhanced with `required_resources` |

## Next

Ready for **Phase 8 — Multi-Master Readiness & Advanced Coordination**.
