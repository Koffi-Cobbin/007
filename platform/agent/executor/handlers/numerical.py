"""Chunked numerical processing workload handler — Monte Carlo, summation."""

from executor.plugin_base import BaseWorkloadHandler


class NumericalHandler(BaseWorkloadHandler):
    name = "numerical"
    description = "Chunked numerical processing: Monte Carlo, range summation"
    version = "1.0.0"

    def validate(self, payload):
        errors = []
        if not payload.get("operation"):
            errors.append("Missing required field: 'operation'")
        return errors

    def execute(self, payload, timeout):
        operation = payload.get("operation", "sum")
        iterations = payload.get("iterations", 1000000)
        chunk_index = payload.get("chunk_index", 0)
        total_chunks = payload.get("total_chunks", 1)

        chunk_size = iterations // total_chunks
        start = chunk_index * chunk_size
        end = start + chunk_size if chunk_index < total_chunks - 1 else iterations

        if operation == "monte_carlo":
            import random
            inside = 0
            for _ in range(start, end):
                x, y = random.random(), random.random()
                if x * x + y * y <= 1:
                    inside += 1
            pi_estimate = 4.0 * inside / (end - start) if (end - start) > 0 else 0
            return _success({
                "operation": operation, "chunk_index": chunk_index,
                "range": {"start": start, "end": end},
                "inside_circle": inside, "pi_estimate": pi_estimate,
            })

        if operation == "sum":
            total = sum(range(start, end))
            return _success({
                "operation": operation, "chunk_index": chunk_index,
                "range": {"start": start, "end": end}, "result": total,
            })

        return _error("UNKNOWN_OPERATION", f"Unknown numerical operation: {operation}")


def _success(output: dict) -> dict:
    return {"status": "completed", "output": output, "error": None, "logs": ""}

def _error(code: str, message: str) -> dict:
    return {"status": "failed", "output": {}, "error": {"code": code, "message": message}, "logs": f"Error [{code}]: {message}\n"}
