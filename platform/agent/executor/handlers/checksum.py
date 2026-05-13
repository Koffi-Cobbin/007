"""Checksum / hash workload handler — MD5, SHA-256, SHA-512."""

import hashlib
from pathlib import Path

from executor.plugin_base import BaseWorkloadHandler


class ChecksumHandler(BaseWorkloadHandler):
    name = "checksum"
    description = "Compute hash values (MD5, SHA-256, SHA-512) for files"
    version = "1.0.0"

    def validate(self, payload):
        errors = []
        if not payload.get("files"):
            errors.append("Missing required field: 'files'")
        algo = payload.get("algorithm", "sha256")
        if algo and not hasattr(hashlib, algo):
            errors.append(f"Unsupported algorithm: '{algo}'")
        return errors

    def execute(self, payload, timeout):
        files = payload.get("files", [])
        algorithm = payload.get("algorithm", "sha256")
        expected = payload.get("expected", {})

        if not files:
            return _error("NO_FILES", "No files provided")

        hasher_fn = getattr(hashlib, algorithm, None)
        if hasher_fn is None:
            return _error("INVALID_ALGORITHM", f"Unsupported algorithm: {algorithm}")

        results = []
        total_bytes = 0
        for f in files:
            src = Path(f)
            if not src.exists():
                results.append({"file": f, "hash": None, "status": "skipped", "reason": "not found"})
                continue
            try:
                h = hasher_fn()
                with open(src, "rb") as fin:
                    for chunk in iter(lambda: fin.read(65536), b""):
                        h.update(chunk)
                        total_bytes += len(chunk)
                digest = h.hexdigest()
                match = None
                if f in expected:
                    match = digest == expected[f]
                results.append({
                    "file": f, "hash": digest, "algorithm": algorithm,
                    "status": "completed", "match": match,
                })
            except OSError as exc:
                results.append({"file": f, "hash": None, "status": "failed", "error": str(exc)})

        return _success({
            "results": results, "total": len(results),
            "succeeded": sum(1 for r in results if r["status"] == "completed"),
            "bytes_processed": total_bytes,
        })


def _success(output: dict) -> dict:
    return {"status": "completed", "output": output, "error": None, "logs": ""}

def _error(code: str, message: str) -> dict:
    return {"status": "failed", "output": {}, "error": {"code": code, "message": message}, "logs": f"Error [{code}]: {message}\n"}
