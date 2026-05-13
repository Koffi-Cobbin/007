"""Python function execution workload handler — inline code runner."""

from executor.plugin_base import BaseWorkloadHandler


class PythonExecutionHandler(BaseWorkloadHandler):
    name = "python_execution"
    description = "Execute a small inline Python function on the agent"
    version = "1.0.0"

    def validate(self, payload):
        errors = []
        if not payload.get("code"):
            errors.append("Missing required field: 'code'")
        return errors

    def execute(self, payload, timeout):
        code = payload.get("code", "")
        function_name = payload.get("function", "")
        args = payload.get("args", [])
        chunk = payload.get("chunk")

        if not code:
            return _error("NO_CODE", "No Python code provided")

        namespace = {"__builtins__": __builtins__}
        try:
            exec(code, namespace)
        except SyntaxError as exc:
            return _error("SYNTAX_ERROR", str(exc))

        if function_name and function_name in namespace:
            try:
                fn = namespace[function_name]
                call_args = chunk.get("args", args) if isinstance(chunk, dict) else args
                if not isinstance(call_args, (list, tuple)):
                    call_args = [call_args]
                result = fn(*call_args)
                return _success({
                    "function": function_name, "result": result, "args": call_args,
                })
            except Exception as exc:
                return _error("EXECUTION_ERROR", str(exc))

        return _success({
            "function": function_name or "executed", "result": None,
            "note": f"Code executed but function '{function_name}' not found in namespace" if function_name else "Code executed",
        })


def _success(output: dict) -> dict:
    return {"status": "completed", "output": output, "error": None, "logs": ""}

def _error(code: str, message: str) -> dict:
    return {"status": "failed", "output": {}, "error": {"code": code, "message": message}, "logs": f"Error [{code}]: {message}\n"}
