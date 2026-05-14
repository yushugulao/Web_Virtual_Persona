from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.backend.core.config import get_settings  # noqa: E402
from app.backend.document_reader.adapters import parser_registry  # noqa: E402


def _torch_status() -> dict[str, Any]:
    try:
        import torch
    except Exception as exc:  # pragma: no cover - environment dependent.
        return {"installed": False, "error": str(exc)}
    cuda_available = bool(torch.cuda.is_available())
    payload: dict[str, Any] = {
        "installed": True,
        "version": getattr(torch, "__version__", ""),
        "cuda_available": cuda_available,
        "cuda_device_count": int(torch.cuda.device_count()) if cuda_available else 0,
    }
    if cuda_available:
        payload["cuda_device_name"] = torch.cuda.get_device_name(0)
    return payload


def _run_command(command: list[str], *, timeout: float = 30) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return {"available": False, "error": f"{command[0]} not found"}
    except Exception as exc:  # pragma: no cover - environment-specific.
        return {"available": False, "error": str(exc)}
    return {
        "available": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _docker_status() -> dict[str, Any]:
    status: dict[str, Any] = {
        "docker": _run_command(["docker", "--version"]),
        "compose": _run_command(["docker", "compose", "version"]),
    }
    if status["docker"].get("available"):
        status["gpu_smoke"] = _run_command(
            [
                "docker",
                "run",
                "--rm",
                "--gpus",
                "all",
                "--entrypoint",
                "nvidia-smi",
                "ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:latest-nvidia-gpu-sm120",
            ],
            timeout=120,
        )
    else:
        status["gpu_smoke"] = {"available": False, "error": "docker not available"}
    return status


def _paddle_http_status() -> dict[str, Any]:
    settings = get_settings()
    endpoint = settings.document_reader_paddleocr_vl_endpoint.strip().rstrip("/")
    payload: dict[str, Any] = {
        "mode": settings.document_reader_paddleocr_vl_mode,
        "endpoint": endpoint,
        "enabled": settings.document_reader_enable_paddleocr_vl,
    }
    if not endpoint:
        return payload | {"available": False, "reason": "endpoint empty"}
    try:
        import httpx

        response = httpx.get(endpoint + "/docs", timeout=5)
    except Exception as exc:
        return payload | {"available": False, "reason": str(exc)}
    return payload | {
        "available": response.status_code < 500,
        "status_code": response.status_code,
        "layout_endpoint": endpoint + "/layout-parsing",
        "restructure_endpoint": endpoint + "/restructure-pages",
    }


def _paddle_worker_status() -> dict[str, Any]:
    settings = get_settings()
    configured_python = settings.document_reader_paddleocr_vl_python.strip()
    if configured_python:
        runtime_python = Path(configured_python)
    else:
        runtime_python = (
            Path(settings.document_reader_model_cache_dir)
            / "runtimes"
            / "paddleocr_vl"
            / ".venv"
            / "Scripts"
            / "python.exe"
        )
    worker = ROOT / "scripts" / "document_reader" / "paddleocr_vl_worker.py"
    payload: dict[str, Any] = {
        "mode": settings.document_reader_paddleocr_vl_mode,
        "python": str(runtime_python),
        "python_exists": runtime_python.exists(),
        "worker": str(worker),
        "worker_exists": worker.exists(),
        "device": settings.document_reader_paddleocr_vl_device,
        "timeout_seconds": settings.document_reader_paddleocr_vl_timeout_seconds,
        "cache_dir": str(Path(settings.document_reader_model_cache_dir)),
        "cache_on_c_drive": str(Path(settings.document_reader_model_cache_dir)).lower().startswith("c:"),
    }
    if not runtime_python.exists() or not worker.exists():
        return payload | {"check_ok": False, "reason": "runtime python or worker missing"}
    try:
        completed = subprocess.run(
            [
                str(runtime_python),
                str(worker),
                "--check",
                "--cache-dir",
                str(settings.document_reader_model_cache_dir),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except Exception as exc:  # pragma: no cover - environment-specific.
        return payload | {"check_ok": False, "reason": str(exc)}
    worker_payload: dict[str, Any] = {}
    for line in reversed(completed.stdout.splitlines()):
        try:
            parsed = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            worker_payload = parsed
            break
    return payload | {
        "check_ok": completed.returncode == 0 and bool(worker_payload.get("ok")),
        "returncode": completed.returncode,
        "stdout_json": worker_payload,
        "stderr": completed.stderr.strip(),
    }


def _marker_surya_worker_status() -> dict[str, Any]:
    settings = get_settings()
    configured_python = settings.document_reader_marker_surya_python.strip()
    if configured_python:
        runtime_python = Path(configured_python)
    else:
        runtime_root = (
            Path(settings.document_reader_model_cache_dir)
            / "runtimes"
            / "marker_surya"
            / ".venv"
        )
        windows_python = runtime_root / "Scripts" / "python.exe"
        runtime_python = windows_python if windows_python.exists() else runtime_root / "bin" / "python"
    worker = ROOT / "scripts" / "document_reader" / "marker_surya_worker.py"
    payload: dict[str, Any] = {
        "python": str(runtime_python),
        "python_exists": runtime_python.exists(),
        "worker": str(worker),
        "worker_exists": worker.exists(),
        "enabled": settings.document_reader_enable_marker_surya,
        "device": settings.document_reader_marker_surya_device,
        "timeout_seconds": settings.document_reader_marker_surya_timeout_seconds,
        "cache_dir": str(Path(settings.document_reader_model_cache_dir)),
        "cache_on_c_drive": str(Path(settings.document_reader_model_cache_dir)).lower().startswith("c:"),
    }
    if not runtime_python.exists() or not worker.exists():
        return payload | {"check_ok": False, "reason": "runtime python or worker missing"}
    try:
        completed = subprocess.run(
            [
                str(runtime_python),
                str(worker),
                "--check",
                "--cache-dir",
                str(settings.document_reader_model_cache_dir),
                "--device",
                settings.document_reader_marker_surya_device,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except Exception as exc:  # pragma: no cover - environment-specific.
        return payload | {"check_ok": False, "reason": str(exc)}
    worker_payload: dict[str, Any] = {}
    for line in reversed(completed.stdout.splitlines()):
        try:
            parsed = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            worker_payload = parsed
            break
    return payload | {
        "check_ok": completed.returncode == 0 and bool(worker_payload.get("ok")),
        "returncode": completed.returncode,
        "stdout_json": worker_payload,
        "stderr": completed.stderr.strip(),
    }


def build_report() -> dict[str, Any]:
    settings = get_settings()
    backends: list[dict[str, Any]] = []
    for adapter in parser_registry(settings):
        availability = adapter.available()
        backends.append(
            {
                "name": availability.name,
                "enabled": availability.enabled,
                "available": availability.available,
                "reason": availability.reason,
            }
        )
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "model_cache_dir": str(Path(settings.document_reader_model_cache_dir)),
        "torch": _torch_status(),
        "docker": _docker_status(),
        "marker_surya_worker": _marker_surya_worker_status(),
        "paddleocr_vl_http": _paddle_http_status(),
        "paddleocr_vl_worker": _paddle_worker_status(),
        "backends": backends,
    }


def _runtime_line(payload: dict[str, Any]) -> str:
    runtime = payload.get("stdout_json") or {}
    versions = runtime.get("versions") or {}
    parts = []
    parser_runtime = versions.get("parser_runtime")
    torch_version = versions.get("torch")
    cuda_available = versions.get("cuda_available")
    device_name = versions.get("cuda_device_name")
    capability = versions.get("cuda_device_capability")
    if parser_runtime:
        parts.append(f"runtime={parser_runtime}")
    if torch_version:
        parts.append(f"torch={torch_version}")
    if cuda_available:
        parts.append(f"cuda_available={cuda_available}")
    if device_name:
        parts.append(f"gpu={device_name}")
    if capability:
        parts.append(f"capability={capability}")
    return " / ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local document-reader backend availability.")
    parser.add_argument("--json", action="store_true", help="Print only JSON output.")
    args = parser.parse_args()
    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("Document Reader Backend Check")
    print(f"Python: {report['python'].split()[0]}")
    print(f"Platform: {report['platform']}")
    print(f"Model cache: {report['model_cache_dir']}")
    torch = report["torch"]
    if torch.get("installed"):
        device = torch.get("cuda_device_name") or "CPU"
        print(f"Torch: {torch.get('version')} / CUDA: {torch.get('cuda_available')} / {device}")
    else:
        print(f"Torch: not installed ({torch.get('error')})")
    worker = report["paddleocr_vl_worker"]
    marker = report["marker_surya_worker"]
    marker_status = "OK" if marker.get("check_ok") else "OFF"
    marker_c_warning = " / WARNING: cache on C drive" if marker.get("cache_on_c_drive") else ""
    print(
        f"Marker/Surya worker: {marker_status} / enabled={marker.get('enabled')} / "
        f"device={marker.get('device')}{marker_c_warning}"
    )
    marker_runtime = _runtime_line(marker)
    if marker_runtime:
        print(f"  {marker_runtime}")
    if marker.get("reason"):
        print(f"  reason: {marker['reason']}")
    if marker.get("stderr"):
        print(f"  stderr: {marker['stderr'][:240]}")
    worker_status = "OK" if worker.get("check_ok") else "OFF"
    c_warning = " / WARNING: cache on C drive" if worker.get("cache_on_c_drive") else ""
    print(
        f"PaddleOCR-VL worker: {worker_status} / mode={worker.get('mode')} / "
        f"device={worker.get('device')}{c_warning}"
    )
    if worker.get("reason"):
        print(f"  reason: {worker['reason']}")
    if worker.get("stderr"):
        print(f"  stderr: {worker['stderr'][:240]}")
    docker = report["docker"]
    docker_status = "OK" if docker.get("docker", {}).get("available") else "OFF"
    compose_status = "OK" if docker.get("compose", {}).get("available") else "OFF"
    gpu_status = "OK" if docker.get("gpu_smoke", {}).get("available") else "OFF"
    print(f"Docker: {docker_status} / Compose: {compose_status} / GPU passthrough: {gpu_status}")
    if docker.get("docker", {}).get("error"):
        print(f"  docker: {docker['docker']['error']}")
    if docker.get("gpu_smoke", {}).get("error"):
        print(f"  gpu smoke: {docker['gpu_smoke']['error']}")
    http = report["paddleocr_vl_http"]
    http_status = "OK" if http.get("available") else "OFF"
    print(
        f"PaddleOCR-VL HTTP: {http_status} / mode={http.get('mode')} / "
        f"endpoint={http.get('endpoint') or '<empty>'}"
    )
    if http.get("reason"):
        print(f"  reason: {http['reason']}")
    print()
    for backend in report["backends"]:
        mark = "OK" if backend["available"] else "OFF"
        enabled = "enabled" if backend["enabled"] else "disabled"
        reason = f" - {backend['reason']}" if backend["reason"] else ""
        print(f"[{mark}] {backend['name']} ({enabled}){reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
