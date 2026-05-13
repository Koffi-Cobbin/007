"""File processing workload handler — copy, compress, transform files."""

import shutil
import tempfile
import uuid
from pathlib import Path

from executor.plugin_base import BaseWorkloadHandler


class FileProcessingHandler(BaseWorkloadHandler):
    name = "file_processing"
    description = "Copy, move, compress, or transform files"
    version = "1.0.0"

    def validate(self, payload):
        errors = []
        if not payload.get("files"):
            errors.append("Missing required field: 'files'")
        return errors

    def execute(self, payload, timeout):
        files = payload.get("files", [])
        operation = payload.get("operation", "copy")
        target_dir = Path(payload.get("target_dir", tempfile.gettempdir())) / f"dtask_{uuid.uuid4().hex[:8]}"

        if not files:
            return _error("NO_FILES", "No files provided")

        results = []
        for f in files:
            src = Path(f)
            if not src.exists():
                results.append({"file": f, "status": "skipped", "reason": "not found"})
                continue
            try:
                if operation == "copy":
                    dst = target_dir / src.name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    results.append({"file": f, "status": "copied", "destination": str(dst)})
                elif operation == "compress":
                    import gzip
                    dst = target_dir / f"{src.name}.gz"
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    with open(src, "rb") as fin, gzip.open(dst, "wb") as fout:
                        shutil.copyfileobj(fin, fout)
                    results.append({"file": f, "status": "compressed", "destination": str(dst)})
                else:
                    results.append({"file": f, "status": "skipped", "reason": f"unsupported operation: {operation}"})
            except OSError as exc:
                results.append({"file": f, "status": "failed", "error": str(exc)})

        return _success({
            "results": results, "total": len(results),
            "succeeded": sum(1 for r in results if r["status"] in ("copied", "compressed")),
        })


def _success(output: dict) -> dict:
    return {"status": "completed", "output": output, "error": None, "logs": ""}

def _error(code: str, message: str) -> dict:
    return {"status": "failed", "output": {}, "error": {"code": code, "message": message}, "logs": f"Error [{code}]: {message}\n"}
