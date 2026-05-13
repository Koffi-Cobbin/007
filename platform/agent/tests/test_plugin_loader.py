"""
Tests for the Phase 7 plugin system — discovery, registry, handlers.
"""

import pytest

from executor.loader import discover_handlers, get_handler, reload_handlers
from executor.plugin_base import BaseWorkloadHandler


class TestPluginDiscovery:
    """Verify the plugin loader finds all built-in handlers."""

    def setup_method(self):
        reload_handlers()  # fresh discovery for each test

    def test_discovers_all_six_builtin_handlers(self):
        registry = discover_handlers()
        expected = {"checksum", "file_processing", "image_processing",
                     "data_transform", "python_execution", "numerical"}
        found = set(registry.keys())
        missing = expected - found
        assert not missing, f"Missing handlers: {missing}"
        assert len(registry) >= 6

    def test_each_handler_is_instance(self):
        registry = discover_handlers()
        for name, handler in registry.items():
            assert isinstance(handler, BaseWorkloadHandler), f"{name} is not a BaseWorkloadHandler"
            assert handler.name, f"{name} has empty name"
            assert handler.version, f"{name} has empty version"
            assert hasattr(handler, "validate"), f"{name} missing validate()"
            assert hasattr(handler, "execute"), f"{name} missing execute()"

    def test_get_handler_returns_none_for_unknown(self):
        assert get_handler("nonexistent_type") is None

    def test_get_handler_returns_correct_type(self):
        handler = get_handler("checksum")
        assert handler is not None
        assert handler.name == "checksum"
        assert handler.description


class TestHandlerValidation:
    """Each built-in handler's validate() rejects bad payloads."""

    def test_checksum_requires_files(self):
        handler = get_handler("checksum")
        errors = handler.validate({"algorithm": "sha256"})
        assert len(errors) > 0
        assert "files" in errors[0]

    def test_checksum_valid_passes(self):
        handler = get_handler("checksum")
        errors = handler.validate({"files": ["a.iso"], "algorithm": "sha256"})
        assert errors == []

    def test_file_processing_requires_files(self):
        handler = get_handler("file_processing")
        assert handler.validate({}) != []

    def test_python_execution_requires_code(self):
        handler = get_handler("python_execution")
        assert handler.validate({}) != []

    def test_numerical_requires_operation(self):
        handler = get_handler("numerical")
        assert handler.validate({}) != []


class TestHandlerExecution:
    """Each built-in handler can execute a valid payload."""

    def test_checksum_returns_metrics(self):
        handler = get_handler("checksum")
        # No real files — should return failure but not crash
        result = handler.execute({"files": ["/nonexistent/file.bin"]}, timeout=30)
        assert result["status"] in ("completed", "failed")
        assert "output" in result

    def test_python_execution_runs_code(self):
        handler = get_handler("python_execution")
        result = handler.execute({
            "code": "def add(a,b): return {'sum': a+b}",
            "function": "add",
            "args": [2, 3],
        }, timeout=30)
        assert result["status"] == "completed"
        assert result["output"]["result"]["sum"] == 5

    def test_numerical_computes_sum(self):
        handler = get_handler("numerical")
        result = handler.execute({
            "operation": "sum", "iterations": 100,
            "chunk_index": 0, "total_chunks": 1,
        }, timeout=30)
        assert result["status"] == "completed"
        assert result["output"]["result"] == sum(range(0, 100))

    def test_unknown_operation(self):
        handler = get_handler("numerical")
        result = handler.execute({"operation": "bogus"}, timeout=30)
        assert result["status"] == "failed"
