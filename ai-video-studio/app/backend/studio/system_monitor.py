"""GPU, disk and process monitoring. Every metric may be unavailable; callers
must show "unavailable" rather than inventing numbers."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import psutil

_GPU_FIELDS = ["name", "utilization.gpu", "memory.used", "memory.total", "temperature.gpu", "power.draw"]
_cache: dict = {"ts": 0.0, "value": None}


def _nvidia_smi() -> str | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        win = Path("C:/Windows/System32/nvidia-smi.exe")
        exe = str(win) if win.is_file() else None
    return exe


def gpu_stats(max_age_s: float = 3.0) -> list[dict] | None:
    """Per-GPU stats from nvidia-smi, cached briefly. None when unavailable."""
    now = time.monotonic()
    if now - _cache["ts"] < max_age_s:
        return _cache["value"]
    exe = _nvidia_smi()
    value = None
    if exe:
        try:
            out = subprocess.run(
                [exe, f"--query-gpu={','.join(_GPU_FIELDS)}", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0:
                value = []
                for line in out.stdout.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) < len(_GPU_FIELDS):
                        continue

                    def num(s):
                        try:
                            return float(s)
                        except ValueError:
                            return None

                    value.append({
                        "name": parts[0],
                        "utilization_pct": num(parts[1]),
                        "memory_used_mb": num(parts[2]),
                        "memory_total_mb": num(parts[3]),
                        "temperature_c": num(parts[4]),
                        "power_w": num(parts[5]),
                    })
        except (OSError, subprocess.TimeoutExpired):
            value = None
    _cache.update(ts=now, value=value)
    return value


def disk_stats(path: Path) -> dict | None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return {
        "path": str(path),
        "total_gb": round(usage.total / 1024**3, 1),
        "free_gb": round(usage.free / 1024**3, 1),
        "used_pct": round(100 * (usage.total - usage.free) / usage.total, 1) if usage.total else None,
    }


def dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def running_blocklisted(names: list[str]) -> list[str]:
    """Which of the given process names (case-insensitive, .exe optional) are running."""
    if not names:
        return []
    wanted = {n.lower().removesuffix(".exe") for n in names}
    found = set()
    for proc in psutil.process_iter(["name"]):
        try:
            n = (proc.info.get("name") or "").lower().removesuffix(".exe")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if n in wanted:
            found.add(n)
    return sorted(found)


def system_snapshot(data_dir: Path) -> dict:
    vm = psutil.virtual_memory()
    return {
        "cpu_pct": psutil.cpu_percent(interval=None),
        "ram_used_gb": round((vm.total - vm.available) / 1024**3, 1),
        "ram_total_gb": round(vm.total / 1024**3, 1),
        "gpus": gpu_stats(),
        "disk": disk_stats(data_dir),
    }
