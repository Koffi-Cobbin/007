# WORKLOADS.md — v1 Workload Types and Qualification

## v1 Workload Types

The first version supports exactly **six workload types**. Each represents a category of task that is easy to split into sub-tasks, straightforward to verify, and well-suited to a local-network cluster of desktops and laptops.

### 1. File Processing

| Field | Detail |
|---|---|
| **Description** | Copy, move, rename, compress, or transform files across nodes. |
| **Common use cases** | Batch file organization, archive extraction, format conversion, file permission changes. |
| **Inputs** | List of file paths, target directory, operation type, parameters. |
| **Output** | Operation results summary (success/failure per file, bytes processed). |
| **Splittable?** | Yes — files can be distributed across nodes by file list sharding. |

**Example task payload:**
```json
{
  "task_type": "file_processing",
  "inputs": {
    "files": ["/data/images/photo001.jpg", "/data/images/photo002.jpg"],
    "parameters": {
      "operation": "compress",
      "target_format": "jpeg",
      "quality": 85
    }
  }
}
```

---

### 2. Batch Image Processing

| Field | Detail |
|---|---|
| **Description** | Apply image operations (resize, convert, watermark, thumbnail) to a set of images. |
| **Common use cases** | Generating thumbnails, format conversion (PNG→JPEG), applying watermarks, bulk resizing. |
| **Inputs** | List of image paths or URLs, operation parameters (width, height, format, watermark file). |
| **Output** | Processed image paths, per-image status, total bytes processed. |
| **Splittable?** | Yes — images are independent; split by image list sharding. |

**Example task payload:**
```json
{
  "task_type": "image_processing",
  "inputs": {
    "files": ["/images/photo001.png", "/images/photo002.png"],
    "parameters": {
      "resize": { "width": 800, "height": 600 },
      "format": "jpeg",
      "quality": 90,
      "apply_watermark": false
    }
  }
}
```

---

### 3. Checksum / Hash Jobs

| Field | Detail |
|---|---|
| **Description** | Compute hash values (MD5, SHA-256, SHA-512) for a set of files and verify integrity. |
| **Common use cases** | File integrity verification after transfer, duplicate detection, archive validation. |
| **Inputs** | File paths, hash algorithm, expected hashes (optional, for verification). |
| **Output** | Per-file computed hash, match/mismatch status (if expected hashes provided), bytes processed. |
| **Splittable?** | Yes — each file is independently hashable; split by file list sharding. |

**Example task payload:**
```json
{
  "task_type": "checksum",
  "inputs": {
    "files": ["/data/archive.zip", "/data/backup.tar.gz"],
    "parameters": {
      "algorithm": "sha256",
      "expected": {
        "/data/archive.zip": "a1b2c3d4...",
        "/data/backup.tar.gz": null
      }
    }
  }
}
```

---

### 4. Data Transformation

| Field | Detail |
|---|---|
| **Description** | Process structured data (CSV, JSON, XML) — filter, map, reduce, merge, or convert. |
| **Common use cases** | ETL pipelines, log parsing, CSV→JSON conversion, data cleaning, field extraction. |
| **Inputs** | Source data (file path or inline), transformation script/configuration, output format. |
| **Output** | Transformed data path, row counts, bytes processed. |
| **Splittable?** | Yes — if data can be partitioned (e.g., by row ranges or file shards). |

**Example task payload:**
```json
{
  "task_type": "data_transform",
  "inputs": {
    "files": ["/data/logs/server.log"],
    "parameters": {
      "transform_type": "filter",
      "filter_expression": "level == 'ERROR'",
      "output_format": "json",
      "partition": {
        "start_line": 0,
        "end_line": 10000
      }
    }
  }
}
```

---

### 5. Python Function Execution

| Field | Detail |
|---|---|
| **Description** | Execute a small Python function (code string or module path) on the agent. |
| **Common use cases** | Custom computation, parameter sweep, simulation step, data analysis snippet. |
| **Inputs** | Python code string (or module path), function name, arguments. |
| **Output** | Function return value (serialized to JSON), stdout/stderr, execution duration. |
| **Splittable?** | Yes — if the parameter space can be partitioned across nodes. |

**Example task payload:**
```json
{
  "task_type": "python_execution",
  "inputs": {
    "parameters": {
      "source": "inline",
      "code": "def process_chunk(start, end):\n    total = 0\n    for i in range(start, end):\n        total += i ** 2\n    return {'sum': total, 'start': start, 'end': end}",
      "function": "process_chunk",
      "args": [1, 1000000]
    }
  }
}
```

---

### 6. Chunked Numerical Processing

| Field | Detail |
|---|---|
| **Description** | Process a large numerical dataset by splitting it into independent chunks. |
| **Common use cases** | Monte Carlo simulations, matrix operations, statistical analysis on large arrays. |
| **Inputs** | Data file (or inline data), operation parameters, chunk specification. |
| **Output** | Per-chunk results, aggregate summary. |
| **Splittable?** | Yes — the defining characteristic; work is designed to be chunked. |

**Example task payload:**
```json
{
  "task_type": "numerical",
  "inputs": {
    "files": ["/data/simulation_input.csv"],
    "parameters": {
      "operation": "monte_carlo",
      "iterations": 1000000,
      "chunk": {
        "index": 3,
        "total_chunks": 10
      }
    }
  }
}
```

---

## Task Qualification Checklist

For a workload type to be eligible for v1, it must meet **all** of these criteria:

| # | Criterion | Rationale |
|---|---|---|
| 1 | Tasks within a job are **independent** (no cross-node coordination required) | Avoids distributed synchronization complexity in v1 |
| 2 | Inputs can be expressed as **files or serializable data** | Keeps the payload schema simple |
| 3 | Output is a **deterministic function** of the input | Makes verification and retry straightforward |
| 4 | Task can be executed in a **subprocess** | No container runtime required |
| 5 | Task has a **clear timeout limit** | Prevents runaway tasks from blocking the node |
| 6 | Results can be expressed as **JSON-serializable data** | Simplifies result storage and aggregation |
| 7 | Task resources (CPU, memory) are **reasonably estimable** in advance | Enables basic scheduling without profiling |

## Deferred Workload Classes

These workload types are explicitly deferred to v2+:

| Workload | Reason for Deferral |
|---|---|
| **AI inference** | Requires GPU scheduling, model distribution, larger payloads |
| **Distributed rendering** | Long-running, real-time progress reporting, GPU dependency |
| **File synchronization** | Stateful, needs conflict resolution, bidirectional |
| **Sensor aggregation** | Streaming data, real-time requirements |
| **Build/test jobs** | Complex dependency graphs, artifact management |
| **Containerized execution** | Requires Docker/containerd, sandboxing policy |
| **Long-running services** | Different lifecycle model than batch tasks |

## Task Input / Output Schema

### Generic Task Input

All workload types follow this envelope:

```json
{
  "task_id": "uuid",
  "task_type": "string (one of the 6 types)",
  "inputs": {
    "files": ["string"],
    "parameters": {},
    "data": {}
  },
  "timeout_seconds": 300,
  "max_retries": 3
}
```

### Generic Task Output

```json
{
  "task_id": "uuid",
  "status": "completed | failed | cancelled",
  "output": {
    "output_files": ["string"],
    "output_data": {},
    "summary": {
      "items_processed": 100,
      "bytes_processed": 1048576,
      "duration_seconds": 45.2
    }
  },
  "error": {},
  "metrics": {
    "started_at": "2026-05-12T12:00:00Z",
    "completed_at": "2026-05-12T12:00:45Z",
    "peak_memory_mb": 256
  }
}
```

## Adding a New Workload Type (Future)

When a new workload type is needed beyond v1:

1. Add the type to `WORKLOADS.md` with a schema definition
2. Create an executor handler on the agent side
3. Update the capability matching logic in the scheduler
4. Add validation for the new payload schema in the API layer
5. No changes to core orchestration, protocol, or data model should be needed
