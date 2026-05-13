"""
Plugin discovery system — automatically finds ``BaseWorkloadHandler``
subclasses in built-in ``handlers/`` and third-party ``plugins/``
directories.

Usage::

    from executor.loader import discover_handlers, get_handler

    registry = discover_handlers()
    handler = get_handler("checksum")
    if handler:
        result = handler.execute(payload, timeout=300)
"""

import importlib.util
import logging
import sys
from pathlib import Path

from executor.plugin_base import BaseWorkloadHandler

logger = logging.getLogger(__name__)

# Directories to scan (relative to this file's parent) — used in
# development / non-frozen mode where the filesystem is accessible.
SEARCH_DIRS = [
    Path(__file__).parent / "handlers",      # Built-in handlers
    Path(__file__).parent.parent / "plugins",  # Third-party plugins
]

# When running under PyInstaller, files are inside the .exe and the
# dynamic import below won't work.  We fall back to the statically
# imported registry from handlers/__init__.py
_IS_FROZEN = getattr(sys, "frozen", False)

# Cache so we only scan once per process
_registry: dict[str, BaseWorkloadHandler] | None = None


def _load_module_from_path(filepath: Path):
    """Import a Python file as a module given its filesystem path."""
    module_name = f"_plugin_{filepath.stem}"
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    return None


def discover_handlers() -> dict[str, BaseWorkloadHandler]:
    """Scan all plugin directories and return ``{name: handler_instance}``.

    Results are cached — subsequent calls return the same registry.
    """
    global _registry
    if _registry is not None:
        return _registry

    handlers: dict[str, BaseWorkloadHandler] = {}

    # ── PyInstaller fallback ──────────────────────────────────────
    if _IS_FROZEN:
        try:
            from executor.handlers import _BUILTIN_HANDLERS as builtins
            for name, cls in builtins.items():
                handlers[name] = cls()
                logger.info("Discovered handler: '%s' v%s (built-in)", name, handlers[name].version)
        except ImportError:
            logger.warning("Built-in handler registry not available")
        _registry = handlers
        logger.info("Plugin discovery complete — %d handler(s) registered (frozen)", len(handlers))
        return handlers

    # ── Development mode (dynamic filesystem discovery) ───────────
    for search_dir in SEARCH_DIRS:
        if not search_dir.is_dir():
            logger.debug("Plugin dir not found: %s", search_dir)
            continue

        for py_file in sorted(search_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue  # skip __init__.py, _private.py

            module = _load_module_from_path(py_file)
            if module is None:
                logger.warning("Failed to load plugin: %s", py_file)
                continue

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseWorkloadHandler)
                    and attr is not BaseWorkloadHandler
                ):
                    instance = attr()
                    name = instance.name or py_file.stem
                    handlers[name] = instance
                    logger.info(
                        "Discovered handler: '%s' v%s (from %s)",
                        name, instance.version, py_file.name,
                    )

    _registry = handlers
    logger.info("Plugin discovery complete — %d handler(s) registered", len(handlers))
    return handlers


def get_handler(task_type: str) -> BaseWorkloadHandler | None:
    """Return the handler instance for *task_type*, or ``None``."""
    return discover_handlers().get(task_type)


def reload_handlers():
    """Force re-discovery on the next call to ``discover_handlers()``."""
    global _registry
    _registry = None
