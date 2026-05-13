"""
Built-in workload handler plugins.

Each module defines a ``BaseWorkloadHandler`` subclass.
Explicit imports here ensure PyInstaller traces them correctly
when building a standalone executable, while the plugin loader's
dynamic discovery still works for third-party plugins.
"""

from .checksum import ChecksumHandler
from .file_processing import FileProcessingHandler
from .image_processing import ImageProcessingHandler
from .data_transform import DataTransformHandler
from .python_execution import PythonExecutionHandler
from .numerical import NumericalHandler

# Registry of all built-in handlers for PyInstaller fallback
_BUILTIN_HANDLERS = {
    "checksum": ChecksumHandler,
    "file_processing": FileProcessingHandler,
    "image_processing": ImageProcessingHandler,
    "data_transform": DataTransformHandler,
    "python_execution": PythonExecutionHandler,
    "numerical": NumericalHandler,
}
