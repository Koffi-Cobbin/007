"""
Tests for the task executor and workload handlers.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from executor.runner import TaskRunner


class TestTaskRunner:
    def test_unknown_task_type(self):
        runner = TaskRunner()
        result = runner.execute({"task_id": "t-1", "task_type": "unknown", "payload": {}})
        assert result["status"] == "failed"
        assert result["error"]["code"] == "UNKNOWN_TASK_TYPE"

    def test_handler_crash_is_caught(self):
        runner = TaskRunner()
        # Pass a payload type that the handler can't destructure
        result = runner.execute({"task_id": "t-1", "task_type": "file_processing", "payload": "not-a-dict"})
        assert result["status"] == "failed"
        assert result["error"]["code"] in ("HANDLER_CRASH", "NO_FILES")

    def test_result_includes_duration(self):
        runner = TaskRunner()
        result = runner.execute({"task_id": "t-1", "task_type": "checksum", "payload": {"files": []}})
        assert "duration_seconds" in result.get("metrics", {})


class TestChecksumHandler:
    def test_checksum_no_files(self):
        runner = TaskRunner()
        result = runner.execute({"task_id": "t-1", "task_type": "checksum", "payload": {"files": []}})
        assert result["status"] == "failed"
        assert result["error"]["code"] == "NO_FILES"

    def test_checksum_single_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            tmp = f.name
        try:
            runner = TaskRunner()
            result = runner.execute({
                "task_id": "t-1",
                "task_type": "checksum",
                "payload": {"files": [tmp], "algorithm": "sha256"},
            })
            assert result["status"] == "completed"
            assert result["output"]["results"][0]["status"] == "completed"
            assert len(result["output"]["results"][0]["hash"]) == 64  # SHA-256 hex length
        finally:
            os.unlink(tmp)

    def test_checksum_file_not_found(self):
        runner = TaskRunner()
        result = runner.execute({
            "task_id": "t-1",
            "task_type": "checksum",
            "payload": {"files": ["/nonexistent/file.bin"]},
        })
        assert result["status"] == "completed"  # partial success
        assert result["output"]["results"][0]["status"] == "skipped"

    def test_checksum_invalid_algorithm(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("data")
            tmp = f.name
        try:
            runner = TaskRunner()
            result = runner.execute({
                "task_id": "t-1",
                "task_type": "checksum",
                "payload": {"files": [tmp], "algorithm": "nosuch"},
            })
            assert result["status"] == "failed"
            assert result["error"]["code"] == "INVALID_ALGORITHM"
        finally:
            os.unlink(tmp)


class TestFileProcessingHandler:
    def test_copy_files(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test data")
            src = f.name
        try:
            runner = TaskRunner()
            result = runner.execute({
                "task_id": "t-1",
                "task_type": "file_processing",
                "payload": {"files": [src], "operation": "copy"},
            })
            assert result["status"] == "completed"
            assert result["output"]["results"][0]["status"] == "copied"
            assert Path(result["output"]["results"][0]["destination"]).exists()
        finally:
            os.unlink(src)

    def test_no_files(self):
        runner = TaskRunner()
        result = runner.execute({
            "task_id": "t-1",
            "task_type": "file_processing",
            "payload": {"files": [], "operation": "copy"},
        })
        assert result["status"] == "failed"
        assert result["error"]["code"] == "NO_FILES"


class TestPythonExecutionHandler:
    def test_simple_function(self):
        runner = TaskRunner()
        code = "def add(a, b): return a + b"
        result = runner.execute({
            "task_id": "t-1",
            "task_type": "python_execution",
            "payload": {"code": code, "function": "add", "args": [3, 5]},
        })
        assert result["status"] == "completed"
        assert result["output"]["result"] == 8

    def test_syntax_error(self):
        runner = TaskRunner()
        result = runner.execute({
            "task_id": "t-1",
            "task_type": "python_execution",
            "payload": {"code": "def broken(:", "function": "broken"},
        })
        assert result["status"] == "failed"
        assert result["error"]["code"] == "SYNTAX_ERROR"

    def test_no_code(self):
        runner = TaskRunner()
        result = runner.execute({
            "task_id": "t-1",
            "task_type": "python_execution",
            "payload": {"code": ""},
        })
        assert result["status"] == "failed"
        assert result["error"]["code"] == "NO_CODE"


class TestNumericalHandler:
    def test_sum(self):
        runner = TaskRunner()
        result = runner.execute({
            "task_id": "t-1",
            "task_type": "numerical",
            "payload": {
                "operation": "sum",
                "iterations": 100,
                "chunk_index": 0,
                "total_chunks": 2,
            },
        })
        assert result["status"] == "completed"
        # Sum of 0..49 = 1225
        assert result["output"]["result"] == sum(range(0, 50))
        assert result["output"]["chunk_index"] == 0

    def test_monte_carlo(self):
        runner = TaskRunner()
        result = runner.execute({
            "task_id": "t-1",
            "task_type": "numerical",
            "payload": {
                "operation": "monte_carlo",
                "iterations": 10000,
                "chunk_index": 0,
                "total_chunks": 1,
            },
        })
        assert result["status"] == "completed"
        pi = result["output"]["pi_estimate"]
        assert 2.0 < pi < 4.0  # should be close to 3.14

    def test_unknown_operation(self):
        runner = TaskRunner()
        result = runner.execute({
            "task_id": "t-1",
            "task_type": "numerical",
            "payload": {"operation": "unknown_op"},
        })
        assert result["status"] == "failed"
        assert result["error"]["code"] == "UNKNOWN_OPERATION"


class TestDataTransformHandler:
    def test_convert_to_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("a,b,c\n1,2,3\n4,5,6\n")
            tmp = f.name
        try:
            runner = TaskRunner()
            result = runner.execute({
                "task_id": "t-1",
                "task_type": "data_transform",
                "payload": {
                    "files": [tmp],
                    "transform_type": "convert",
                    "output_format": "json",
                },
            })
            assert result["status"] == "completed"
            dst = result["output"]["results"][0]["destination"]
            with open(dst) as f:
                data = json.load(f)
            assert "lines" in data
        finally:
            os.unlink(tmp)

    def test_no_files(self):
        runner = TaskRunner()
        result = runner.execute({
            "task_id": "t-1",
            "task_type": "data_transform",
            "payload": {"files": []},
        })
        assert result["status"] == "failed"


class TestImageProcessingHandler:
    def test_no_files(self):
        runner = TaskRunner()
        result = runner.execute({
            "task_id": "t-1",
            "task_type": "image_processing",
            "payload": {"files": []},
        })
        assert result["status"] == "failed"
        assert result["error"]["code"] == "NO_FILES"
