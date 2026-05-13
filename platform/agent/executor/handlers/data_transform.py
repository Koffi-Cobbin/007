"""Data transformation workload handler — filter, map, convert."""

import json
from pathlib import Path

from executor.plugin_base import BaseWorkloadHandler


class DataTransformHandler(BaseWorkloadHandler):
    name = "data_transform"
    description = "Filter, map, reduce, or convert structured data (CSV, JSON, XML)"
    version = "1.0.0"

    def validate(self, payload):
        errors = []
        if not payload.get("files"):
            errors.append("Missing required field: 'files'")
        return errors

    def execute(self, payload, timeout):
        files = payload.get("files", [])
        transform_type = payload.get("transform_type", "convert")
        output_format = payload.get("output_format", "json")
        partition = payload.get("partition")

        if not files:
            return _error("NO_FILES", "No files provided")

        results = []
        for f in files:
            src = Path(f)
            if not src.exists():
                results.append({"file": f, "status": "skipped", "reason": "not found"})
                continue
            try:
                with open(src) as fin:
                    lines = fin.readlines()

                if partition:
                    start = partition.get("start_line", 0)
                    end = partition.get("end_line", len(lines))
                    lines = lines[start:end]

                if transform_type == "filter":
                    expr = payload.get("filter_expression", "")
                    if "ERROR" in expr:
                        lines = [l for l in lines if "ERROR" in l]
                    elif "level" in expr:
                        import re
                        match = re.search(r"level\s*==\s*'(\w+)'", expr)
                        if match:
                            lines = [l for l in lines if match.group(1) in l]

                dst = src.parent / f"{src.stem}_transformed.{output_format}"
                with open(dst, "w") as fout:
                    if output_format == "json":
                        json.dump({"lines": lines, "count": len(lines), "source": str(src)}, fout, indent=2)
                    else:
                        fout.writelines(lines)

                results.append({
                    "file": f, "status": "transformed",
                    "destination": str(dst), "lines_processed": len(lines),
                })
            except OSError as exc:
                results.append({"file": f, "status": "failed", "error": str(exc)})

        return _success({
            "results": results, "total": len(results),
            "succeeded": sum(1 for r in results if r["status"] == "transformed"),
        })


def _success(output: dict) -> dict:
    return {"status": "completed", "output": output, "error": None, "logs": ""}

def _error(code: str, message: str) -> dict:
    return {"status": "failed", "output": {}, "error": {"code": code, "message": message}, "logs": f"Error [{code}]: {message}\n"}
