"""Image processing workload handler — resize, convert, watermark."""

import subprocess
from pathlib import Path

from executor.plugin_base import BaseWorkloadHandler


class ImageProcessingHandler(BaseWorkloadHandler):
    name = "image_processing"
    description = "Resize, convert format, or apply watermarks to images"
    version = "1.0.0"

    def validate(self, payload):
        errors = []
        if not payload.get("files"):
            errors.append("Missing required field: 'files'")
        return errors

    def execute(self, payload, timeout):
        files = payload.get("files", [])
        target_format = payload.get("format", "jpeg")
        resize = payload.get("resize", {})
        quality = payload.get("quality", 85)

        if not files:
            return _error("NO_FILES", "No files provided")

        results = []
        for f in files:
            src = Path(f)
            if not src.exists():
                results.append({"file": f, "status": "skipped", "reason": "not found"})
                continue
            try:
                dst = src.parent / f"{src.stem}_converted.{target_format}"
                cmd = ["convert", str(src)]
                if resize:
                    cmd.extend(["-resize", f"{resize.get('width', 800)}x{resize.get('height', 600)}"])
                cmd.extend(["-quality", str(quality), str(dst)])
                subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)
                results.append({"file": f, "status": "converted", "destination": str(dst)})
            except FileNotFoundError:
                try:
                    from PIL import Image
                    img = Image.open(src)
                    if resize:
                        img = img.resize((resize.get("width", 800), resize.get("height", 600)))
                    dst = src.parent / f"{src.stem}_converted.{target_format}"
                    img.save(dst, format=target_format.upper(), quality=quality)
                    results.append({"file": f, "status": "converted", "destination": str(dst)})
                except ImportError:
                    results.append({"file": f, "status": "skipped", "reason": "neither ImageMagick nor Pillow available"})
            except subprocess.CalledProcessError as exc:
                results.append({"file": f, "status": "failed", "error": exc.stderr.decode() if exc.stderr else str(exc)})

        return _success({
            "results": results, "total": len(results),
            "succeeded": sum(1 for r in results if r["status"] == "converted"),
        })


def _success(output: dict) -> dict:
    return {"status": "completed", "output": output, "error": None, "logs": ""}

def _error(code: str, message: str) -> dict:
    return {"status": "failed", "output": {}, "error": {"code": code, "message": message}, "logs": f"Error [{code}]: {message}\n"}
