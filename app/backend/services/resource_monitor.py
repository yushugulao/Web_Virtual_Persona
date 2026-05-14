from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from app.backend.schemas.status import ResourceUsage


_LAST_CPU_SAMPLE: tuple[float, float] | None = None
_LAST_SYSTEM_CPU_SAMPLE: tuple[int, int] | None = None


def build_resource_usage(*, data_dir: Path, model_dir: Path) -> ResourceUsage:
    psutil_usage = _build_with_psutil(data_dir=data_dir, model_dir=model_dir)
    if psutil_usage is not None:
        return psutil_usage

    memory = _windows_memory_status()
    process_memory_mb = _windows_process_memory_mb()
    return ResourceUsage(
        cpu_percent=_windows_cpu_percent(),
        process_cpu_percent=_process_cpu_percent(),
        memory_total_mb=memory.get("total_mb"),
        memory_used_mb=memory.get("used_mb"),
        memory_percent=memory.get("percent"),
        process_memory_mb=process_memory_mb,
        **_disk_usage_fields(data_dir=data_dir, model_dir=model_dir),
        **_gpu_usage_fields(),
    )


def _build_with_psutil(*, data_dir: Path, model_dir: Path) -> ResourceUsage | None:
    try:
        import psutil  # type: ignore[import-not-found]
    except Exception:
        return None

    try:
        memory = psutil.virtual_memory()
        process = psutil.Process(os.getpid())
        return ResourceUsage(
            cpu_percent=round(float(psutil.cpu_percent(interval=None)), 1),
            process_cpu_percent=round(float(process.cpu_percent(interval=None)), 1),
            memory_total_mb=round(memory.total / 1024 / 1024, 1),
            memory_used_mb=round(memory.used / 1024 / 1024, 1),
            memory_percent=round(float(memory.percent), 1),
            process_memory_mb=round(process.memory_info().rss / 1024 / 1024, 1),
            **_disk_usage_fields(data_dir=data_dir, model_dir=model_dir),
            **_gpu_usage_fields(),
        )
    except Exception:
        return None


def _gpu_usage_fields() -> dict[str, float | str | None]:
    empty = _empty_gpu_usage_fields()
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return empty
    try:
        result = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=index,name,utilization.gpu,memory.total,memory.used,memory.free,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
    except Exception:
        return empty
    if result.returncode != 0:
        return empty
    return _parse_nvidia_smi_csv(result.stdout) or empty


def _empty_gpu_usage_fields() -> dict[str, float | str | None]:
    return {
        "gpu_name": None,
        "gpu_util_percent": None,
        "gpu_memory_total_mb": None,
        "gpu_memory_used_mb": None,
        "gpu_memory_free_mb": None,
        "gpu_memory_percent": None,
        "gpu_temperature_c": None,
        "gpu_power_draw_w": None,
    }


def _parse_nvidia_smi_csv(output: str) -> dict[str, float | str | None] | None:
    rows = [_parse_gpu_row(line) for line in output.splitlines() if line.strip()]
    rows = [row for row in rows if row is not None]
    if not rows:
        return None
    selected = max(
        rows,
        key=lambda row: (
            _safe_float(row.get("gpu_memory_used_mb")) or 0.0,
            _safe_float(row.get("gpu_util_percent")) or 0.0,
        ),
    )
    total = _safe_float(selected.get("gpu_memory_total_mb"))
    used = _safe_float(selected.get("gpu_memory_used_mb"))
    selected["gpu_memory_percent"] = round(used / total * 100, 1) if total and used is not None else None
    return selected


def _parse_gpu_row(line: str) -> dict[str, float | str | None] | None:
    fields = [field.strip() for field in line.split(",")]
    if len(fields) < 8:
        return None
    return {
        "gpu_name": fields[1] or None,
        "gpu_util_percent": _parse_float(fields[2]),
        "gpu_memory_total_mb": _parse_float(fields[3]),
        "gpu_memory_used_mb": _parse_float(fields[4]),
        "gpu_memory_free_mb": _parse_float(fields[5]),
        "gpu_temperature_c": _parse_float(fields[6]),
        "gpu_power_draw_w": _parse_float(fields[7]),
    }


def _parse_float(value: str) -> float | None:
    try:
        cleaned = value.strip().replace("W", "").replace("MiB", "").replace("%", "")
        if not cleaned or cleaned.lower() in {"n/a", "not supported", "[not supported]"}:
            return None
        return round(float(cleaned), 1)
    except ValueError:
        return None


def _safe_float(value: object) -> float | None:
    return float(value) if isinstance(value, (float, int)) else None


def _disk_usage_fields(*, data_dir: Path, model_dir: Path) -> dict[str, float | None]:
    data = _disk_usage(data_dir)
    model = _disk_usage(model_dir)
    return {
        "data_disk_total_gb": data.get("total_gb"),
        "data_disk_free_gb": data.get("free_gb"),
        "data_disk_percent": data.get("percent"),
        "model_disk_total_gb": model.get("total_gb"),
        "model_disk_free_gb": model.get("free_gb"),
        "model_disk_percent": model.get("percent"),
    }


def _disk_usage(path: Path) -> dict[str, float | None]:
    try:
        path = path.resolve()
        probe = path if path.exists() else _nearest_existing_parent(path)
        usage = shutil.disk_usage(probe)
    except Exception:
        return {"total_gb": None, "free_gb": None, "percent": None}
    used = usage.total - usage.free
    percent = (used / usage.total * 100) if usage.total else 0.0
    return {
        "total_gb": round(usage.total / 1024**3, 1),
        "free_gb": round(usage.free / 1024**3, 1),
        "percent": round(percent, 1),
    }


def _nearest_existing_parent(path: Path) -> Path:
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    return current


def _process_cpu_percent() -> float | None:
    global _LAST_CPU_SAMPLE
    now = time.perf_counter()
    process_time = time.process_time()
    if _LAST_CPU_SAMPLE is None:
        _LAST_CPU_SAMPLE = (now, process_time)
        return None
    last_now, last_process_time = _LAST_CPU_SAMPLE
    _LAST_CPU_SAMPLE = (now, process_time)
    elapsed = now - last_now
    if elapsed <= 0:
        return None
    cpu_count = os.cpu_count() or 1
    percent = (process_time - last_process_time) / elapsed / cpu_count * 100
    return round(max(0.0, percent), 1)


def _windows_cpu_percent() -> float | None:
    global _LAST_SYSTEM_CPU_SAMPLE
    if os.name != "nt":
        return None

    idle_time = wintypes.FILETIME()
    kernel_time = wintypes.FILETIME()
    user_time = wintypes.FILETIME()
    try:
        ok = ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        )
    except Exception:
        ok = False
    if not ok:
        return None

    idle = _filetime_to_int(idle_time)
    total = _filetime_to_int(kernel_time) + _filetime_to_int(user_time)
    if _LAST_SYSTEM_CPU_SAMPLE is None:
        _LAST_SYSTEM_CPU_SAMPLE = (idle, total)
        return None
    last_idle, last_total = _LAST_SYSTEM_CPU_SAMPLE
    _LAST_SYSTEM_CPU_SAMPLE = (idle, total)
    total_delta = total - last_total
    idle_delta = idle - last_idle
    if total_delta <= 0:
        return None
    return round(max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100)), 1)


def _filetime_to_int(value: wintypes.FILETIME) -> int:
    return (value.dwHighDateTime << 32) + value.dwLowDateTime


def _windows_memory_status() -> dict[str, float | None]:
    if os.name != "nt":
        return {"total_mb": None, "used_mb": None, "percent": None}

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    try:
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except Exception:
        ok = False
    if not ok:
        return {"total_mb": None, "used_mb": None, "percent": None}
    used = status.ullTotalPhys - status.ullAvailPhys
    return {
        "total_mb": round(status.ullTotalPhys / 1024 / 1024, 1),
        "used_mb": round(used / 1024 / 1024, 1),
        "percent": round(float(status.dwMemoryLoad), 1),
    }


def _windows_process_memory_mb() -> float | None:
    if os.name != "nt":
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_: list[tuple[str, Any]] = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    try:
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        psapi = ctypes.WinDLL("Psapi.dll")
        get_process_memory_info = psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        get_process_memory_info.restype = wintypes.BOOL
        ok = get_process_memory_info(
            handle,
            ctypes.byref(counters),
            counters.cb,
        )
    except Exception:
        ok = False
    if not ok:
        return None
    return round(counters.WorkingSetSize / 1024 / 1024, 1)
