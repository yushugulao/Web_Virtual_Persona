"""Portable deployment wizard for Web Virtual Avatar.

The wizard detects the host, recommends a deployment/model profile, writes
local-only configuration, and can optionally install missing prerequisites from
official sources. Secrets are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import re
import shlex
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = ROOT / "configs" / "deployment_profiles"
DEPENDENCIES_PATH = ROOT / "configs" / "deployment_dependencies.json"
MODEL_SOURCES_PATH = ROOT / "configs" / "model_sources.json"
LOCAL_STATE_DIR = ROOT / ".deploy" / "portable"
DOWNLOAD_DIR = LOCAL_STATE_DIR / "downloads"
GENERATED_ENV = LOCAL_STATE_DIR / "generated.env"
ANSWERS_PATH = LOCAL_STATE_DIR / "answers.local.json"
INSTALL_REPORT_PATH = LOCAL_STATE_DIR / "install_report.json"
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"
OLLAMA_PULL_PROGRESS_RE = re.compile(
    r"pulling\s+[0-9a-f]+:\s*(?P<percent>\d+)%.*?"
    r"(?P<done>[0-9.]+)\s*(?P<done_unit>[KMGT]?B)\s*/\s*"
    r"(?P<total>[0-9.]+)\s*(?P<total_unit>[KMGT]?B)",
    re.IGNORECASE,
)
OLLAMA_PULL_STAGE_PROGRESS_RE = re.compile(
    r"(verifying sha256 digest|writing manifest|success|removing any unused layers)",
    re.IGNORECASE,
)


def _prepend_common_user_bins() -> None:
    """Make freshly installed user tools visible inside the current process."""
    candidates = [
        Path.home() / ".local" / "bin",
        Path.home() / ".cargo" / "bin",
        Path.home() / "AppData" / "Local" / "Microsoft" / "WindowsApps",
    ]
    existing = [str(path) for path in candidates if path.exists()]
    if existing:
        os.environ["PATH"] = os.pathsep.join(existing + [os.environ.get("PATH", "")])


_prepend_common_user_bins()


@dataclass
class CommandInfo:
    name: str
    path: str | None
    version: str | None = None


@dataclass
class GpuInfo:
    available: bool
    name: str | None = None
    vram_mb: int | None = None
    driver_version: str | None = None
    cuda_version: str | None = None
    error: str | None = None


@dataclass
class HostInfo:
    os: str
    machine: str
    python_version: str
    ram_gb: float | None
    disk_free_gb: float | None
    commands: dict[str, CommandInfo]
    gpu: GpuInfo
    ollama_http_ready: bool
    nginx_available: bool
    systemd_available: bool
    ssh_available: bool


@dataclass
class DependencyStatus:
    id: str
    label: str
    required_for: list[str]
    command: str | None
    path: str | None
    version: str | None
    installed: bool
    installable: bool
    manual_url: str | None = None
    note: str | None = None


def run_capture(args: list[str], timeout: int = 15) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 - used for diagnostics
        return 127, "", str(exc)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def run_live(args: list[str], dry_run: bool, timeout: int | None = None) -> int:
    print("$ " + " ".join(str(arg) for arg in args))
    if dry_run:
        return 0
    proc = subprocess.run(args, cwd=ROOT, timeout=timeout, check=False)
    return proc.returncode


def run_live_env(args: list[str], dry_run: bool, env: dict[str, str] | None = None, timeout: int | None = None) -> int:
    print("$ " + " ".join(str(arg) for arg in args))
    if dry_run:
        return 0
    proc = subprocess.run(args, cwd=ROOT, env=env, timeout=timeout, check=False)
    return proc.returncode


def command_info(name: str, version_args: list[str] | None = None) -> CommandInfo:
    path = shutil.which(name)
    version = None
    if path and version_args:
        code, stdout, stderr = run_capture(version_args)
        if code == 0:
            version = (stdout or stderr).splitlines()[0] if (stdout or stderr) else None
    return CommandInfo(name=name, path=path, version=version)


def detect_ram_gb() -> float | None:
    if platform.system().lower().startswith("win"):
        code, stdout, _ = run_capture(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory",
            ]
        )
        if code == 0 and stdout.isdigit():
            return round(int(stdout) / (1024**3), 2)
        return None
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("MemTotal:"):
                kb = int(line.split()[1])
                return round(kb / (1024**2), 2)
    return None


def detect_gpu() -> GpuInfo:
    if not shutil.which("nvidia-smi"):
        return GpuInfo(available=False, error="nvidia-smi not found")
    code, stdout, stderr = run_capture(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ],
        timeout=20,
    )
    if code != 0 or not stdout:
        return GpuInfo(available=False, error=stderr or stdout or "nvidia-smi failed")
    first = stdout.splitlines()[0]
    parts = [part.strip() for part in first.split(",")]
    vram_mb = None
    if len(parts) >= 2:
        try:
            vram_mb = int(float(parts[1]))
        except ValueError:
            vram_mb = None
    return GpuInfo(
        available=True,
        name=parts[0] if parts else None,
        vram_mb=vram_mb,
        driver_version=parts[2] if len(parts) >= 3 else None,
    )


def ollama_ready() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=3) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def detect_host() -> HostInfo:
    npm_version_args = ["npm", "--version"]
    if platform.system().lower().startswith("win"):
        npm_version_args = ["cmd", "/c", "npm", "--version"]
    commands = {
        "git": command_info("git", ["git", "--version"]),
        "uv": command_info("uv", ["uv", "--version"]),
        "node": command_info("node", ["node", "--version"]),
        "npm": command_info("npm", npm_version_args),
        "ollama": command_info("ollama", ["ollama", "--version"]),
        "ssh": command_info("ssh", ["ssh", "-V"]),
        "frpc": command_info("frpc", ["frpc", "--version"]),
        "nginx": command_info("nginx", ["nginx", "-v"]),
        "winget": command_info("winget", ["winget", "--version"]),
        "curl": command_info("curl", ["curl", "--version"]),
        "sudo": command_info("sudo", ["sudo", "-V"]),
        "apt-get": command_info("apt-get", ["apt-get", "--version"]),
        "dnf": command_info("dnf", ["dnf", "--version"]),
        "yum": command_info("yum", ["yum", "--version"]),
        "pacman": command_info("pacman", ["pacman", "--version"]),
        "systemctl": command_info("systemctl", ["systemctl", "--version"]),
    }
    disk = shutil.disk_usage(ROOT)
    return HostInfo(
        os=platform.system(),
        machine=platform.machine(),
        python_version=platform.python_version(),
        ram_gb=detect_ram_gb(),
        disk_free_gb=round(disk.free / (1024**3), 2),
        commands=commands,
        gpu=detect_gpu(),
        ollama_http_ready=ollama_ready(),
        nginx_available=bool(commands["nginx"].path),
        systemd_available=bool(commands["systemctl"].path),
        ssh_available=bool(commands["ssh"].path),
    )


def load_profiles() -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for path in PROFILE_DIR.glob("*.json"):
        if path.name == "deployment_modes.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        profiles[data["id"]] = data
    return profiles


def load_dependency_registry() -> dict[str, Any]:
    if not DEPENDENCIES_PATH.exists():
        return {"dependencies": []}
    return json.loads(DEPENDENCIES_PATH.read_text(encoding="utf-8"))


def load_model_sources() -> dict[str, Any]:
    if not MODEL_SOURCES_PATH.exists():
        return {"models": {}}
    return json.loads(MODEL_SOURCES_PATH.read_text(encoding="utf-8"))


def recommend_profile(host: HostInfo, requested: str | None = None) -> str:
    if requested:
        return requested
    ram = host.ram_gb or 0
    vram = host.gpu.vram_mb or 0
    if host.gpu.available and vram >= 12000 and ram >= 24:
        return "standard_gpu"
    if ram >= 16:
        return "minimal_cpu"
    return "no_model_dev"


def prompt_value(label: str, default: str = "", secret: bool = False) -> str:
    suffix = " [hidden]" if secret else f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def prompt_yes_no(label: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{label} ({suffix}): ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "1", "true", "是"}


def collect_answers(args: argparse.Namespace, host: HostInfo) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    if args.answers:
        answers.update(json.loads(Path(args.answers).read_text(encoding="utf-8")))
    deployment_mode = args.mode or answers.get("deployment_mode")
    profile = None if args.profile in {None, "", "auto"} else args.profile
    profile = profile or answers.get("model_profile")
    if not args.non_interactive and not deployment_mode:
        deployment_mode = prompt_value(
            "Deployment mode (local_lan/direct_public_server/frp_tunnel/compute_backend_frp)",
            "local_lan",
        )
    if not args.non_interactive and not profile:
        profile = prompt_value("Model profile (auto/minimal_cpu/standard_gpu/no_model_dev)", "auto")
    profile = None if profile in {None, "", "auto"} else str(profile)
    selected_profile = recommend_profile(host, profile)
    deployment_mode = deployment_mode or "local_lan"
    answers["deployment_mode"] = deployment_mode
    answers["model_profile"] = selected_profile

    dependency_answers = answers.setdefault("dependencies", {})
    if args.install_missing:
        dependency_answers.setdefault("install_missing", True)
    if args.no_install:
        dependency_answers["install_missing"] = False

    secrets = answers.setdefault("secrets", {})
    if not args.non_interactive and not args.dry_run:
        secrets.setdefault("admin_password", prompt_value("Admin password", "change_me_in_local_env", secret=True))
        secrets.setdefault("smtp_host", prompt_value("SMTP host", ""))
        secrets.setdefault("smtp_username", prompt_value("SMTP username", ""))
        secrets.setdefault("smtp_password", prompt_value("SMTP password / authorization code", "", secret=True))
        secrets.setdefault("smtp_from", prompt_value("SMTP from address", secrets.get("smtp_username", "")))
        secrets.setdefault("deepseek_api_key", prompt_value("DeepSeek API key (optional)", "", secret=True))
    if deployment_mode in {"frp_tunnel", "compute_backend_frp"}:
        tunnel = answers.setdefault("frp_tunnel", {})
        if not args.non_interactive and not args.dry_run:
            tunnel.setdefault("server_host", prompt_value("Public server IP/domain", ""))
            tunnel.setdefault("server_port", int(prompt_value("frps bind port", "7000")))
            tunnel.setdefault("remote_port", int(prompt_value("frp remote backend port on public server", "18001")))
            tunnel.setdefault("frp_token", prompt_value("frp token", "", secret=True))
            tunnel.setdefault("public_url", prompt_value("Public URL", "https://<PUBLIC_SERVER_IP>/"))
            if deployment_mode == "frp_tunnel":
                tunnel.setdefault("deploy_user", prompt_value("SSH deploy user", "deploy-admin"))
                tunnel.setdefault("ssh_key", prompt_value("SSH private key path", "secrets/public_tunnel/deploy_admin_ed25519"))
            if deployment_mode == "compute_backend_frp":
                tunnel.setdefault("backend_host", prompt_value("Local backend host", "127.0.0.1"))
                tunnel.setdefault("backend_port", int(prompt_value("Local backend port", "8001")))
                tunnel.setdefault("proxy_name", prompt_value("frp proxy name", "web-avatar-backend"))
    return answers


def build_env(profile: dict[str, Any], answers: dict[str, Any]) -> dict[str, str]:
    env = dict(profile.get("env", {}))
    secrets = answers.get("secrets", {})
    if secrets.get("admin_password"):
        env["PERSONA_RAG_AUTH_ADMIN_PASSWORD"] = secrets["admin_password"]
    if secrets.get("smtp_host"):
        env["PERSONA_RAG_SMTP_HOST"] = secrets["smtp_host"]
    if secrets.get("smtp_username"):
        env["PERSONA_RAG_SMTP_USERNAME"] = secrets["smtp_username"]
    if secrets.get("smtp_password"):
        env["PERSONA_RAG_SMTP_PASSWORD"] = secrets["smtp_password"]
    if secrets.get("smtp_from"):
        env["PERSONA_RAG_SMTP_FROM"] = secrets["smtp_from"]
    if secrets.get("deepseek_api_key"):
        env["PERSONA_RAG_DEEPSEEK_API_KEY"] = secrets["deepseek_api_key"]
    mode = answers.get("deployment_mode", "local_lan")
    env["PERSONA_RAG_DEPLOYMENT_MODE"] = mode
    env["PERSONA_RAG_DEPLOYMENT_PROFILE"] = profile.get("id", "")
    if mode in {"direct_public_server", "frp_tunnel", "compute_backend_frp"}:
        env["PERSONA_RAG_AUTH_TRUST_PROXY_HEADERS"] = "true"
        env["VITE_API_BASE_URL"] = ""
    public_url = answers.get("frp_tunnel", {}).get("public_url") or answers.get("public_url")
    if public_url:
        env["PERSONA_RAG_PUBLIC_URL"] = public_url

    paths = answers.get("dependencies", {}).get("paths", {})
    if paths.get("ollama"):
        env["PERSONA_RAG_OLLAMA_EXECUTABLE"] = paths["ollama"]
    if paths.get("frpc"):
        env["PERSONA_RAG_FRPC_EXECUTABLE"] = paths["frpc"]
    return env


def render_env_file(env: dict[str, str]) -> str:
    lines = [
        "# Generated by scripts/deploy/portable_deploy.py.",
        "# Keep this file local. Do not commit secrets.",
    ]
    for key in sorted(env):
        value = str(env[key])
        lines.append(f"{key}={value}")
    lines.append("")
    return "\n".join(lines)


def write_local_files(answers: dict[str, Any], env: dict[str, str], dry_run: bool) -> None:
    if dry_run:
        return
    LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)
    redacted = json.loads(json.dumps(answers))
    for group in ("secrets", "frp_tunnel"):
        if isinstance(redacted.get(group), dict):
            for key in list(redacted[group]):
                if any(token in key for token in ("password", "key", "token")):
                    redacted[group][key] = "<configured>"
    ANSWERS_PATH.write_text(json.dumps(redacted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    GENERATED_ENV.write_text(render_env_file(env), encoding="utf-8", newline="\n")
    env_path = ROOT / ".env"
    if not env_path.exists():
        source = ROOT / ".env.windows.example" if platform.system().lower().startswith("win") else ROOT / ".env.linux.example"
        if not source.exists():
            source = ROOT / ".env.example"
        shutil.copy2(source, env_path)
    current = env_path.read_text(encoding="utf-8", errors="ignore")
    begin = "# BEGIN portable deployment overrides"
    end = "# END portable deployment overrides"
    block = f"{begin}\n{render_env_file(env)}{end}\n"
    if begin in current and end in current:
        before = current.split(begin, 1)[0].rstrip()
        after = current.split(end, 1)[1].lstrip()
        new_text = before + "\n\n" + block + ("\n" + after if after else "")
    else:
        new_text = current.rstrip() + "\n\n" + block
    env_path.write_text(new_text, encoding="utf-8", newline="\n")
    print(f"Wrote local answers to {ANSWERS_PATH}")
    print(f"Wrote generated env overrides to {GENERATED_ENV}")
    if current:
        print("Updated portable deployment overrides in .env")


def dependency_platform_key(os_name: str | None = None) -> str:
    name = (os_name or platform.system()).lower()
    if name.startswith("win"):
        return "windows"
    if name.startswith("linux"):
        return "linux"
    return name


def command_from_host(host: HostInfo, command: str | None) -> CommandInfo:
    if not command:
        return CommandInfo(name="", path=None)
    return host.commands.get(command) or command_info(command)


def dependency_statuses(
    registry: dict[str, Any],
    host: HostInfo,
    answers: dict[str, Any] | None = None,
) -> list[DependencyStatus]:
    answers = answers or {}
    custom_paths = answers.get("dependencies", {}).get("paths", {})
    platform_key = dependency_platform_key(host.os)
    statuses: list[DependencyStatus] = []
    for dep in registry.get("dependencies", []):
        command = dep.get("command")
        path = custom_paths.get(dep["id"]) or custom_paths.get(command or "")
        version = None
        if path:
            installed = Path(path).exists()
        else:
            info = command_from_host(host, command)
            path = info.path
            version = info.version
            installed = bool(path)
        methods = dep.get("install", {}).get(platform_key, [])
        statuses.append(
            DependencyStatus(
                id=dep["id"],
                label=dep.get("label", dep["id"]),
                required_for=dep.get("required_for", []),
                command=command,
                path=str(path) if path else None,
                version=version,
                installed=installed,
                installable=bool(methods),
                manual_url=dep.get("manual_url"),
                note=dep.get("note"),
            )
        )
    return statuses


def required_dependency_ids(answers: dict[str, Any], profile: dict[str, Any]) -> set[str]:
    mode = answers.get("deployment_mode", "local_lan")
    required = {"uv", "git"}
    if mode in {"local_lan", "direct_public_server", "frp_tunnel"}:
        required.add("node")
    if profile.get("models"):
        required.add("ollama")
    if mode == "frp_tunnel":
        required.add("frp")
        required.add("ssh")
    if mode == "compute_backend_frp":
        required.add("frp")
    if mode == "direct_public_server":
        required.add("nginx")
    return required


def find_dependency(registry: dict[str, Any], dependency_id: str) -> dict[str, Any] | None:
    for dep in registry.get("dependencies", []):
        if dep.get("id") == dependency_id:
            return dep
    return None


def compatible_methods(dep: dict[str, Any], os_name: str | None = None) -> list[dict[str, Any]]:
    return list(dep.get("install", {}).get(dependency_platform_key(os_name), []))


def build_install_plan(
    registry: dict[str, Any],
    statuses: list[DependencyStatus],
    required_ids: set[str],
    os_name: str | None = None,
) -> list[dict[str, Any]]:
    status_by_id = {status.id: status for status in statuses}
    plan: list[dict[str, Any]] = []
    for dependency_id in sorted(required_ids):
        status = status_by_id.get(dependency_id)
        if not status or status.installed:
            continue
        dep = find_dependency(registry, dependency_id)
        if not dep:
            continue
        methods = compatible_methods(dep, os_name)
        method = methods[0] if methods else {"kind": "manual", "url": dep.get("manual_url")}
        plan.append(
            {
                "id": dependency_id,
                "label": dep.get("label", dependency_id),
                "command": dep.get("command"),
                "method": method,
                "manual_url": dep.get("manual_url"),
                "requires_admin": bool(method.get("requires_admin")),
            }
        )
    return plan


def safe_filename_from_url(url: str, fallback: str) -> str:
    name = url.rstrip("/").split("/")[-1] or fallback
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return name or fallback


def remote_content_length(url: str) -> int | None:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "web-avatar-portable-deploy/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.headers.get("Content-Length")
            return int(raw) if raw and raw.isdigit() else None
    except Exception:
        return None


def existing_download_is_complete(url: str, destination: Path) -> bool:
    if not destination.exists() or destination.stat().st_size <= 0:
        return False
    expected = remote_content_length(url)
    if expected is not None:
        return destination.stat().st_size == expected
    suffixes = "".join(destination.suffixes).lower()
    try:
        if suffixes.endswith(".zip"):
            return zipfile.is_zipfile(destination)
        if suffixes.endswith((".tar.gz", ".tgz")):
            with tarfile.open(destination, "r:gz"):
                return True
        if suffixes.endswith(".gguf"):
            with destination.open("rb") as handle:
                return handle.read(4) == b"GGUF"
    except Exception:
        return False
    return False


def download_file(url: str, destination: Path, dry_run: bool = False, retries: int = 2) -> Path:
    print(f"Download: {url}")
    print(f"Target:   {destination}")
    if dry_run:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    if existing_download_is_complete(url, destination):
        print("Using existing completed download.")
        return destination
    curl = shutil.which("curl")
    if curl:
        resume_args: list[str] = []
        if destination.exists() and destination.stat().st_size > 0:
            resume_args = ["-C", "-"]
        command = [
            curl,
            "-fL",
            *resume_args,
            "--retry",
            "3",
            "--retry-delay",
            "2",
            "--connect-timeout",
            "30",
            "--progress-bar",
            "-o",
            str(destination),
            url,
        ]
        code = run_live(command, dry_run=False)
        if code == 0:
            return destination
        if existing_download_is_complete(url, destination):
            print("curl reported a resume error, but the cached file is complete; using it.")
            return destination
        print("curl download failed; falling back to Python downloader.")
    last_error: Exception | None = None
    for attempt in range(1, retries + 2):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "web-avatar-portable-deploy/1.0"})
            with urllib.request.urlopen(request, timeout=180) as response:
                total = int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                start = time.time()
                with destination.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        handle.write(chunk)
                        downloaded += len(chunk)
                        elapsed = max(time.time() - start, 0.001)
                        speed = downloaded / elapsed
                        if total:
                            pct = downloaded / total * 100
                            eta = (total - downloaded) / speed if speed > 0 else 0
                            print(
                                f"\r  {pct:6.2f}%  {downloaded / (1024**2):8.2f}/"
                                f"{total / (1024**2):.2f} MiB  {speed / 1024:.1f} KiB/s  ETA {eta:.0f}s",
                                end="",
                                flush=True,
                            )
                        else:
                            print(
                                f"\r  {downloaded / (1024**2):8.2f} MiB  {speed / 1024:.1f} KiB/s",
                                end="",
                                flush=True,
                            )
                print()
            return destination
        except Exception as exc:  # noqa: BLE001 - surface as install report
            last_error = exc
            print(f"  download attempt {attempt} failed: {exc}")
            time.sleep(min(2 * attempt, 8))
    raise RuntimeError(f"failed to download {url}: {last_error}")


def install_linux_package(package_name: str, dry_run: bool) -> None:
    """Install a small system package through the host package manager."""
    command = (
        "SUDO=''; "
        "if [ \"$(id -u)\" -ne 0 ]; then SUDO=sudo; fi; "
        f"if command -v {package_name} >/dev/null 2>&1; then exit 0; fi; "
        "if command -v apt-get >/dev/null 2>&1; then "
        f"$SUDO apt-get update && $SUDO apt-get install -y {package_name}; "
        "elif command -v dnf >/dev/null 2>&1; then "
        f"$SUDO dnf install -y {package_name}; "
        "elif command -v yum >/dev/null 2>&1; then "
        f"$SUDO yum install -y {package_name}; "
        "elif command -v pacman >/dev/null 2>&1; then "
        f"$SUDO pacman -Sy --noconfirm {package_name}; "
        "else "
        f"echo 'No supported package manager found. Install {package_name} manually.'; exit 1; "
        "fi"
    )
    code = run_live(["sh", "-c", command], dry_run=dry_run)
    if code != 0:
        raise RuntimeError(f"failed to install system package {package_name}")


def install_ollama_linux_archive(method: dict[str, Any], dry_run: bool) -> None:
    """Install Ollama on Linux without the opaque pipe-to-tar installer path."""
    url = method.get("url") or "https://ollama.com/download/ollama-linux-amd64.tar.zst"
    filename = method.get("filename") or "ollama-linux-amd64.tar.zst"
    archive = DOWNLOAD_DIR / "ollama" / filename
    print("Installing Ollama from the official Linux archive.")
    print("This archive is large because it includes model runners; slow networks may take a while.")
    install_linux_package("zstd", dry_run=dry_run)
    download_file(url, archive, dry_run=dry_run, retries=3)
    command = f"zstd -dc {shlex.quote(str(archive))} | tar -xf - -C /usr/local"
    code = run_live(["sh", "-c", command], dry_run=dry_run, timeout=None)
    if code != 0:
        raise RuntimeError(f"Ollama archive extraction failed with exit code {code}")
    if not dry_run:
        code, stdout, stderr = run_capture(["ollama", "--version"], timeout=20)
        if code != 0:
            raise RuntimeError(f"Ollama installed but validation failed: {stderr or stdout}")


def github_latest_asset_url(repo: str, pattern: str) -> tuple[str, str]:
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    request = urllib.request.Request(api_url, headers={"User-Agent": "web-avatar-portable-deploy/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    regex = re.compile(pattern)
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if regex.search(name):
            return asset["browser_download_url"], name
    raise RuntimeError(f"no release asset matched {repo}: {pattern}")


def extract_archive(archive_path: Path, destination: Path, dry_run: bool) -> None:
    print(f"Extract:  {archive_path} -> {destination}")
    if dry_run:
        return
    destination.mkdir(parents=True, exist_ok=True)
    suffixes = "".join(archive_path.suffixes).lower()
    if suffixes.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as zip_file:
            zip_file.extractall(destination)
    elif suffixes.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(destination)
    else:
        raise RuntimeError(f"unsupported archive: {archive_path}")


def method_commands(method: dict[str, Any]) -> list[list[str]]:
    commands = method.get("commands", [])
    return [[str(part) for part in command] for command in commands]


def install_dependency_action(action: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    method = action["method"]
    kind = method.get("kind", "manual")
    result = {"id": action["id"], "method": kind, "ok": False, "error": None}
    try:
        if kind == "manual":
            print(f"{action['label']}: manual install required: {action.get('manual_url')}")
            result["ok"] = False
            result["error"] = "manual_install_required"
        elif kind == "command":
            for command in method_commands(method):
                code = run_live(command, dry_run)
                if code != 0:
                    raise RuntimeError(f"command failed with exit code {code}: {' '.join(command)}")
            result["ok"] = True
        elif kind == "download_run":
            url = method["url"]
            filename = method.get("filename") or safe_filename_from_url(url, f"{action['id']}.download")
            target = DOWNLOAD_DIR / action["id"] / filename
            download_file(url, target, dry_run=dry_run)
            command = [str(part).replace("{download}", str(target)) for part in method.get("run", [])]
            if command:
                code = run_live(command, dry_run)
                if code != 0:
                    raise RuntimeError(f"installer failed with exit code {code}: {' '.join(command)}")
            result["ok"] = True
        elif kind == "github_latest_archive":
            if dry_run:
                name = f"{action['id']}-latest-archive"
                url = f"https://github.com/{method['repo']}/releases/latest"
            else:
                url, name = github_latest_asset_url(method["repo"], method["asset_pattern"])
            target = DOWNLOAD_DIR / action["id"] / name
            download_file(url, target, dry_run=dry_run)
            extract_archive(target, ROOT / method.get("extract_to", ".deploy/portable/tools"), dry_run=dry_run)
            result["ok"] = True
        elif kind == "ollama_linux_archive":
            install_ollama_linux_archive(method, dry_run=dry_run)
            result["ok"] = True
        else:
            raise RuntimeError(f"unsupported install method: {kind}")
    except Exception as exc:  # noqa: BLE001 - report to user
        result["error"] = str(exc)
        print(f"Install failed for {action['label']}: {exc}")
    return result


def run_install_plan(plan: list[dict[str, Any]], dry_run: bool) -> list[dict[str, Any]]:
    if not plan:
        return []
    print("\n== Missing dependency install plan ==")
    for action in plan:
        admin = " (requires admin/root)" if action.get("requires_admin") else ""
        print(f"- {action['label']}: {action['method'].get('description', action['method'].get('kind'))}{admin}")
    results: list[dict[str, Any]] = []
    for action in plan:
        results.append(install_dependency_action(action, dry_run=dry_run))
    if not dry_run:
        LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)
        INSTALL_REPORT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote install report to {INSTALL_REPORT_PATH}")
    return results


def find_ollama_executable(answers: dict[str, Any] | None = None) -> str | None:
    answers = answers or {}
    custom = answers.get("dependencies", {}).get("paths", {}).get("ollama")
    if custom and Path(custom).exists():
        return str(Path(custom))
    found = shutil.which("ollama")
    if found:
        return found
    if platform.system().lower().startswith("win"):
        candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.exists():
            return str(candidate)
    return None


def start_ollama_if_needed(ollama: str, dry_run: bool) -> None:
    if ollama_ready():
        return
    print("Ollama HTTP API is not ready; attempting to start ollama serve.")
    if dry_run:
        return
    log_dir = LOCAL_STATE_DIR / "logs"
    pid_dir = LOCAL_STATE_DIR / "pids"
    log_dir.mkdir(parents=True, exist_ok=True)
    pid_dir.mkdir(parents=True, exist_ok=True)
    stdout = (log_dir / "ollama.out.log").open("a", encoding="utf-8")
    stderr = (log_dir / "ollama.err.log").open("a", encoding="utf-8")
    env = os.environ.copy()
    env.setdefault("OLLAMA_HOST", "127.0.0.1:11434")
    env.setdefault("OLLAMA_MODELS", str(ROOT / "models" / "ollama"))
    proc = subprocess.Popen([ollama, "serve"], cwd=ROOT, stdout=stdout, stderr=stderr, env=env)
    (pid_dir / "ollama.pid").write_text(str(proc.pid), encoding="utf-8")
    for _ in range(20):
        if ollama_ready():
            return
        time.sleep(1)
    print("Ollama was started, but the HTTP API is not ready yet.")


def installed_ollama_models() -> set[str]:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return set()
    names = set()
    for item in data.get("models", []):
        name = item.get("name") or item.get("model")
        if name:
            names.add(name)
    return names


def bytes_from_ollama_size(value: str, unit: str) -> float:
    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
    }
    return float(value) * multipliers.get(unit.upper(), 1)


def extract_ollama_pull_progress(text: str) -> tuple[int, float] | None:
    """Return the highest percent/transferred byte pair visible in Ollama pull output."""
    best: tuple[int, float] | None = None
    for match in OLLAMA_PULL_PROGRESS_RE.finditer(text):
        percent = int(match.group("percent"))
        transferred = bytes_from_ollama_size(match.group("done"), match.group("done_unit"))
        if best is None or (percent, transferred) > best:
            best = (percent, transferred)
    return best


def run_ollama_stream(
    args: list[str],
    dry_run: bool,
    *,
    stall_timeout_seconds: int | None = None,
    timeout_seconds: int | None = None,
    progress_stall_timeout_seconds: int | None = None,
) -> dict[str, Any]:
    print("$ " + " ".join(shlex.quote(str(part)) for part in args))
    if dry_run:
        return {"ok": True, "dry_run": True, "tail": []}
    if stall_timeout_seconds is None:
        stall_timeout_seconds = int(os.getenv("PERSONA_RAG_MODEL_PULL_STALL_TIMEOUT_SECONDS", "240"))
    if timeout_seconds is None:
        timeout_seconds = int(os.getenv("PERSONA_RAG_MODEL_PULL_TIMEOUT_SECONDS", "7200"))
    if progress_stall_timeout_seconds is None:
        progress_stall_timeout_seconds = int(os.getenv("PERSONA_RAG_MODEL_PULL_PROGRESS_STALL_TIMEOUT_SECONDS", "600"))
    proc = subprocess.Popen(
        args,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    chunk_queue: queue.Queue[bytes | None] = queue.Queue()
    assert proc.stdout is not None

    def _reader() -> None:
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                chunk_queue.put(chunk)
        finally:
            chunk_queue.put(None)

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    output_buffer = ""
    started_at = time.monotonic()
    last_output_at = started_at
    last_progress_at = started_at
    last_progress_percent = -1
    last_progress_bytes = -1.0
    is_pull_command = len(args) >= 2 and Path(str(args[0])).name.startswith("ollama") and args[1] == "pull"
    reader_done = False
    failure_reason: str | None = None
    while True:
        try:
            chunk = chunk_queue.get(timeout=0.5)
        except queue.Empty:
            chunk = b""
        if chunk is None:
            reader_done = True
        elif chunk:
            now = time.monotonic()
            last_output_at = now
            text = chunk.decode("utf-8", errors="replace")
            output_buffer = (output_buffer + text)[-20000:]
            print(text, end="", flush=True)
            pull_progress = extract_ollama_pull_progress(text)
            if pull_progress:
                percent, transferred = pull_progress
                if percent > last_progress_percent or transferred > last_progress_bytes:
                    last_progress_percent = percent
                    last_progress_bytes = transferred
                    last_progress_at = now
            elif OLLAMA_PULL_STAGE_PROGRESS_RE.search(text):
                last_progress_at = now
        now = time.monotonic()
        if proc.poll() is not None and reader_done:
            break
        if timeout_seconds > 0 and now - started_at > timeout_seconds:
            failure_reason = "timeout"
        elif (
            is_pull_command
            and progress_stall_timeout_seconds > 0
            and now - last_progress_at > progress_stall_timeout_seconds
        ):
            failure_reason = "no_progress_timeout"
        elif stall_timeout_seconds > 0 and now - last_output_at > stall_timeout_seconds:
            failure_reason = "no_output_timeout"
        if failure_reason:
            print(f"\nModel source stalled: {failure_reason}. Trying next source if available.")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
            break
    reader.join(timeout=2)
    while not chunk_queue.empty():
        chunk = chunk_queue.get_nowait()
        if chunk:
            text = chunk.decode("utf-8", errors="replace")
            output_buffer = (output_buffer + text)[-20000:]
            print(text, end="", flush=True)
    output_tail = output_buffer.replace("\r", "\n").splitlines()[-20:]
    return {
        "ok": proc.returncode == 0 and failure_reason is None,
        "returncode": proc.returncode,
        "tail": output_tail,
        "error": failure_reason,
    }


def ollama_tags_contain(model: str) -> bool:
    return model in installed_ollama_models()


def safe_model_dir_name(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model)


def create_ollama_model_from_gguf(ollama: str, target_model: str, gguf_path: Path, dry_run: bool) -> dict[str, Any]:
    import_dir = LOCAL_STATE_DIR / "model_imports" / safe_model_dir_name(target_model)
    import_dir.mkdir(parents=True, exist_ok=True)
    modelfile = import_dir / "Modelfile"
    modelfile.write_text(f"FROM {gguf_path.as_posix()}\nPARAMETER num_ctx 8192\n", encoding="utf-8")
    print(f"Importing GGUF into Ollama as {target_model}.")
    return run_ollama_stream([ollama, "create", target_model, "-f", str(modelfile)], dry_run=dry_run)


def pull_ollama_model_via_source(ollama: str, model: str, source: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    kind = source.get("kind", "ollama_registry")
    label = source.get("label") or kind
    timeout_seconds = source.get("timeout_seconds")
    stall_timeout_seconds = source.get("stall_timeout_seconds")
    progress_stall_timeout_seconds = source.get("progress_stall_timeout_seconds")
    print(f"\n== Model source for {model}: {label} ==")
    if kind == "ollama_registry":
        source_model = source.get("model") or model
        result = run_ollama_stream(
            [ollama, "pull", source_model],
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            stall_timeout_seconds=stall_timeout_seconds,
            progress_stall_timeout_seconds=progress_stall_timeout_seconds,
        )
        result.update({"source_kind": kind, "source_model": source_model})
        return result
    if kind == "ollama_copy":
        source_model = source["source_model"]
        target_model = source.get("target_model") or model
        pull_result = run_ollama_stream(
            [ollama, "pull", source_model],
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            stall_timeout_seconds=stall_timeout_seconds,
            progress_stall_timeout_seconds=progress_stall_timeout_seconds,
        )
        if not pull_result.get("ok"):
            pull_result.update({"source_kind": kind, "source_model": source_model, "copy_to": target_model})
            return pull_result
        copy_result = run_ollama_stream([ollama, "cp", source_model, target_model], dry_run=dry_run)
        copy_result.update({"source_kind": kind, "source_model": source_model, "copy_to": target_model})
        return copy_result
    if kind == "gguf_import":
        url = source["url"]
        filename = source.get("filename") or safe_filename_from_url(url, f"{safe_model_dir_name(model)}.gguf")
        target_model = source.get("target_model") or model
        gguf_path = DOWNLOAD_DIR / "models" / safe_model_dir_name(model) / filename
        if dry_run:
            print(f"Would download GGUF: {url} -> {gguf_path}")
            print(f"Would run: {ollama} create {target_model} -f <generated Modelfile>")
            return {"ok": True, "dry_run": True, "source_kind": kind, "url": url}
        download_file(url, gguf_path, dry_run=False, retries=3)
        result = create_ollama_model_from_gguf(ollama, target_model, gguf_path, dry_run=False)
        result.update({"source_kind": kind, "url": url, "file": str(gguf_path)})
        return result
    return {"ok": False, "error": f"unsupported_model_source:{kind}", "source_kind": kind}


def pull_ollama_model(ollama: str, model: str, dry_run: bool, model_sources: dict[str, Any] | None = None) -> dict[str, Any]:
    print(f"\n== Pulling Ollama model: {model} ==")
    if dry_run:
        sources = (model_sources or {}).get("models", {}).get(model, {}).get("sources") or [{"kind": "ollama_registry", "model": model}]
        for source in sources:
            pull_ollama_model_via_source(ollama, model, source, dry_run=True)
        return {"model": model, "ok": True, "dry_run": True}
    sources = (model_sources or {}).get("models", {}).get(model, {}).get("sources") or [{"kind": "ollama_registry", "model": model}]
    attempts: list[dict[str, Any]] = []
    for index, source in enumerate(sources, start=1):
        result = pull_ollama_model_via_source(ollama, model, source, dry_run=False)
        result["attempt"] = index
        attempts.append(result)
        if result.get("ok") and ollama_tags_contain(model):
            return {"model": model, "ok": True, "attempts": attempts, "source": result.get("source_kind")}
        if result.get("ok") and source.get("kind") == "ollama_registry":
            return {"model": model, "ok": True, "attempts": attempts, "source": "ollama_registry"}
        print(f"Model source failed or did not create {model}; trying the next source.")
    return {"model": model, "ok": False, "attempts": attempts, "error": "all_model_sources_failed"}


def pull_required_models(models: list[str], answers: dict[str, Any], dry_run: bool) -> list[dict[str, Any]]:
    if not models:
        return []
    if answers.get("deployment_mode") == "compute_backend_frp":
        os.environ.setdefault("OLLAMA_MODELS", str(ROOT / "models" / "ollama"))
    ollama = find_ollama_executable(answers)
    if not ollama:
        print("Ollama executable not found. Run portable_deploy.py --install-missing or provide dependencies.paths.ollama.")
        return [{"model": model, "ok": False, "error": "ollama_not_found"} for model in models]
    start_ollama_if_needed(ollama, dry_run)
    installed = installed_ollama_models() if not dry_run else set()
    model_sources = load_model_sources()
    results = []
    for model in models:
        if model in installed:
            print(f"Model already installed: {model}")
            results.append({"model": model, "ok": True, "skipped": True})
            continue
        results.append(pull_ollama_model(ollama, model, dry_run=dry_run, model_sources=model_sources))
    return results


def find_frpc_executable(answers: dict[str, Any] | None = None) -> str | None:
    answers = answers or {}
    custom = answers.get("dependencies", {}).get("paths", {}).get("frpc") or os.environ.get("PERSONA_RAG_FRPC_EXECUTABLE")
    if custom and Path(custom).exists():
        return str(Path(custom))
    found = shutil.which("frpc")
    if found:
        return found
    executable_name = "frpc.exe" if platform.system().lower().startswith("win") else "frpc"
    for candidate in (LOCAL_STATE_DIR / "tools").glob(f"**/{executable_name}"):
        if candidate.exists():
            return str(candidate)
    return None


def wait_http_ready(url: str, timeout_seconds: int = 60) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if 200 <= response.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def stop_pid_file(pid_path: Path, dry_run: bool) -> None:
    if not pid_path.exists():
        return
    pid_text = pid_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not pid_text.isdigit():
        return
    if dry_run:
        print(f"Would stop process from {pid_path}: {pid_text}")
        return
    try:
        if platform.system().lower().startswith("win"):
            subprocess.run(["taskkill", "/PID", pid_text, "/F"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["kill", pid_text], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        pid_path.unlink(missing_ok=True)


def run_uv_sync(dry_run: bool) -> None:
    print("\n== Installing Python dependencies ==")
    if dry_run:
        print("$ uv sync")
        return
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv was not found after dependency installation.")
    subprocess.run([uv, "sync"], cwd=ROOT, check=True)


def write_frpc_config(answers: dict[str, Any], dry_run: bool) -> Path:
    tunnel = answers.get("frp_tunnel", {})
    config_path = LOCAL_STATE_DIR / "frpc-compute-backend.toml"
    server_host = tunnel.get("server_host")
    server_port = int(tunnel.get("server_port") or 7000)
    remote_port = int(tunnel.get("remote_port") or 18001)
    backend_host = tunnel.get("backend_host") or "127.0.0.1"
    backend_port = int(tunnel.get("backend_port") or 8001)
    proxy_name = tunnel.get("proxy_name") or "web-avatar-backend"
    token = tunnel.get("frp_token") or ""
    if not server_host or not token:
        raise RuntimeError("compute_backend_frp requires frp_tunnel.server_host and frp_tunnel.frp_token.")
    text = "\n".join(
        [
            f'serverAddr = "{server_host}"',
            f"serverPort = {server_port}",
            "",
            "[auth]",
            'method = "token"',
            f'token = "{token}"',
            "",
            "[[proxies]]",
            f'name = "{proxy_name}"',
            'type = "tcp"',
            f'localIP = "{backend_host}"',
            f"localPort = {backend_port}",
            f"remotePort = {remote_port}",
            "",
        ]
    )
    if dry_run:
        print(f"Would write frpc config to {config_path}")
        return config_path
    LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)
    config_path.write_text(text, encoding="utf-8", newline="\n")
    return config_path


def start_backend_process(env: dict[str, str], answers: dict[str, Any], dry_run: bool) -> None:
    tunnel = answers.get("frp_tunnel", {})
    backend_host = tunnel.get("backend_host") or "127.0.0.1"
    backend_port = int(tunnel.get("backend_port") or 8001)
    health_url = f"http://{backend_host}:{backend_port}/health"
    if wait_http_ready(health_url, timeout_seconds=3):
        print(f"Backend is already healthy at {health_url}")
        return
    print("\n== Starting backend ==")
    if dry_run:
        print(f"$ uv run uvicorn app.backend.main:app --host {backend_host} --port {backend_port}")
        return
    pid_dir = LOCAL_STATE_DIR / "pids"
    log_dir = LOCAL_STATE_DIR / "logs"
    pid_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    stop_pid_file(pid_dir / "backend.pid", dry_run=False)
    process_env = os.environ.copy()
    process_env.update(env)
    process_env.setdefault("OLLAMA_HOST", "http://127.0.0.1:11434")
    stdout = (log_dir / "backend.out.log").open("a", encoding="utf-8")
    stderr = (log_dir / "backend.err.log").open("a", encoding="utf-8")
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "app.backend.main:app", "--host", backend_host, "--port", str(backend_port)],
        cwd=ROOT,
        env=process_env,
        stdout=stdout,
        stderr=stderr,
    )
    (pid_dir / "backend.pid").write_text(str(proc.pid), encoding="utf-8")
    if not wait_http_ready(health_url, timeout_seconds=90):
        raise RuntimeError(f"Backend did not become healthy at {health_url}. Check {log_dir / 'backend.err.log'}")
    print(f"Backend is healthy at {health_url}")


def start_frpc_process(answers: dict[str, Any], dry_run: bool) -> None:
    print("\n== Starting frpc tunnel ==")
    frpc = find_frpc_executable(answers)
    if not frpc:
        if dry_run:
            frpc = "frpc"
        else:
            raise RuntimeError("frpc executable was not found after dependency installation.")
    config_path = write_frpc_config(answers, dry_run=dry_run)
    if dry_run:
        print(f"$ {frpc} -c {config_path}")
        return
    pid_dir = LOCAL_STATE_DIR / "pids"
    log_dir = LOCAL_STATE_DIR / "logs"
    pid_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    stop_pid_file(pid_dir / "frpc.pid", dry_run=False)
    stdout = (log_dir / "frpc.out.log").open("a", encoding="utf-8")
    stderr = (log_dir / "frpc.err.log").open("a", encoding="utf-8")
    proc = subprocess.Popen([frpc, "-c", str(config_path)], cwd=ROOT, stdout=stdout, stderr=stderr)
    (pid_dir / "frpc.pid").write_text(str(proc.pid), encoding="utf-8")
    time.sleep(5)
    if proc.poll() is not None:
        tail = (log_dir / "frpc.err.log").read_text(encoding="utf-8", errors="ignore")[-2000:]
        raise RuntimeError(f"frpc exited early. stderr tail:\n{tail}")
    print("frpc process is running.")


def verify_public_endpoint(answers: dict[str, Any], dry_run: bool) -> None:
    public_url = (answers.get("frp_tunnel", {}).get("public_url") or "").rstrip("/")
    if not public_url:
        return
    health_url = f"{public_url}/health"
    print(f"\n== Verifying public health: {health_url} ==")
    if dry_run:
        return
    if not wait_http_ready(health_url, timeout_seconds=90):
        raise RuntimeError(f"Public health check failed: {health_url}")
    print(f"Public health check succeeded: {health_url}")


def run_compute_backend_frp(answers: dict[str, Any], profile: dict[str, Any], env: dict[str, str], dry_run: bool) -> None:
    run_uv_sync(dry_run=dry_run)
    if profile.get("models") and not dry_run:
        os.environ.setdefault("OLLAMA_MODELS", str(ROOT / "models" / "ollama"))
    if profile.get("models"):
        results = pull_required_models(profile["models"], answers, dry_run=dry_run)
        failed = [item for item in results if not item.get("ok")]
        if failed:
            raise RuntimeError("Model pull failed; switch profile or retry after checking Ollama logs.")
    start_backend_process(env, answers, dry_run=dry_run)
    start_frpc_process(answers, dry_run=dry_run)
    verify_public_endpoint(answers, dry_run=dry_run)


def print_dependency_summary(statuses: list[DependencyStatus], required_ids: set[str]) -> None:
    print("\n== Dependency status ==")
    for status in statuses:
        marker = "required" if status.id in required_ids else "optional"
        state = "found" if status.installed else "missing"
        path = f" at {status.path}" if status.path else ""
        print(f"- {status.label} ({marker}): {state}{path}")


def print_summary(host: HostInfo, profile: dict[str, Any], answers: dict[str, Any]) -> None:
    print("\n== Host detection ==")
    print(json.dumps(asdict(host), ensure_ascii=False, indent=2))
    print("\n== Recommended deployment ==")
    print(f"mode: {answers['deployment_mode']}")
    print(f"model_profile: {profile['id']} - {profile.get('label', '')}")
    print("models: " + (", ".join(profile.get("models", [])) or "(none)"))


def next_steps(answers: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    mode = answers.get("deployment_mode", "local_lan")
    steps = []
    if platform.system().lower().startswith("win"):
        steps.append(r".\scripts\deploy\portable_deploy.ps1 -InstallMissing")
        steps.append(r".\scripts\setup\bootstrap_windows.ps1")
        if profile.get("models"):
            steps.append(r".\scripts\models\pull_required_models.ps1 -Models " + ",".join(profile["models"]))
        steps.append(r".\scripts\dev\start_all_windows.ps1")
        if mode == "frp_tunnel":
            steps.append(r".\scripts\deploy\bootstrap_public_ecs_frp.ps1 -ServerHost <PUBLIC_SERVER_IP>")
            steps.append(r".\scripts\deploy\deploy_public_demo.ps1 -ServerHost <PUBLIC_SERVER_IP>")
    else:
        steps.append("bash scripts/deploy/portable_deploy.sh --install-missing")
        steps.append("bash scripts/setup/bootstrap_linux.sh")
        if profile.get("models"):
            steps.append("bash scripts/models/pull_required_models.sh " + " ".join(profile["models"]))
        steps.append("bash scripts/dev/start_all_linux.sh")
        if mode == "direct_public_server":
            steps.append("configure Nginx from deploy/public/nginx-web-avatar-direct.conf.example")
            steps.append("configure systemd from deploy/public/web-avatar-backend.service.example")
        if mode == "compute_backend_frp":
            steps.append("python scripts/deploy/portable_deploy.py --mode compute_backend_frp --profile standard_gpu --install-missing --pull-models")
            steps.append("keep the public server running Nginx + frps; this host runs backend/Ollama/frpc only")
    return steps


def should_install(args: argparse.Namespace, answers: dict[str, Any], missing_required: bool) -> bool:
    if args.no_install:
        return False
    if args.install_missing or args.dry_run_install or (args.yes and missing_required):
        return True
    dep_answers = answers.get("dependencies", {})
    if "install_missing" in dep_answers:
        return bool(dep_answers["install_missing"])
    if args.non_interactive or args.dry_run or not missing_required:
        return False
    return prompt_yes_no("Missing required dependencies were detected. Install them now from official sources?", False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="detect and plan without writing files or running installers")
    parser.add_argument("--dry-run-install", action="store_true", help="plan dependency installs without writing files or running installers")
    parser.add_argument("--check-only", action="store_true", help="only print host/dependency status")
    parser.add_argument("--install-missing", action="store_true", help="install missing required dependencies from official sources")
    parser.add_argument("--no-install", action="store_true", help="never install missing dependencies")
    parser.add_argument("--yes", action="store_true", help="assume yes for safe installer prompts")
    parser.add_argument("--non-interactive", action="store_true", help="do not prompt; use answers/defaults")
    parser.add_argument("--answers", help="JSON answer file for automated runs")
    parser.add_argument("--profile", choices=["auto", "minimal_cpu", "standard_gpu", "no_model_dev"], help="model profile override")
    parser.add_argument(
        "--mode",
        choices=["local_lan", "direct_public_server", "frp_tunnel", "compute_backend_frp"],
        help="deployment mode",
    )
    parser.add_argument("--pull-models", action="store_true", help="pull selected Ollama models after writing config")
    args = parser.parse_args(argv)

    if args.dry_run_install:
        args.dry_run = True
        args.install_missing = True
        args.non_interactive = True

    profiles = load_profiles()
    registry = load_dependency_registry()
    host = detect_host()
    answers = collect_answers(args, host)
    profile = profiles[answers["model_profile"]]
    required_ids = required_dependency_ids(answers, profile)
    statuses = dependency_statuses(registry, host, answers)
    install_plan = build_install_plan(registry, statuses, required_ids)
    env = build_env(profile, answers)

    print_summary(host, profile, answers)
    print_dependency_summary(statuses, required_ids)

    missing_required = bool(install_plan)
    if should_install(args, answers, missing_required):
        run_install_plan(install_plan, dry_run=args.dry_run)
        if not args.dry_run:
            host = detect_host()
            statuses = dependency_statuses(registry, host, answers)
            print_dependency_summary(statuses, required_ids)

    if args.check_only:
        return 0 if not missing_required else 1

    write_local_files(answers, env, args.dry_run)
    if answers.get("deployment_mode") == "compute_backend_frp":
        run_compute_backend_frp(answers, profile, env, dry_run=args.dry_run)
        return 0

    print("\n== Next commands ==")
    for step in next_steps(answers, profile):
        print(step)

    if args.pull_models and profile.get("models"):
        results = pull_required_models(profile["models"], answers, dry_run=args.dry_run)
        failed = [item for item in results if not item.get("ok")]
        if failed:
            print("Some model pulls failed. You can retry, switch to a smaller profile, or use no_model_dev.")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
