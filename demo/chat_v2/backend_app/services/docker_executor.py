from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..settings import settings
from .workspace import resolve_workspace_root, validate_session_id


MANAGED_LABEL_KEY = "deepanalyze.managed"
SESSION_LABEL_KEY = "deepanalyze.session"


@dataclass
class SessionContainerState:
    session_id: str
    container_name: str
    created_by_app: bool
    started_by_app: bool
    last_used_at: float


_DOCKER_LOCK = threading.Lock()
_SESSION_CONTAINERS: dict[str, SessionContainerState] = {}


def _run_docker_command(
    args: list[str],
    *,
    check: bool = True,
    timeout: int | None = 60,
) -> subprocess.CompletedProcess[str]:
    # A default timeout guards every call: a wedged Docker daemon would otherwise
    # hang the caller (and, via _DOCKER_LOCK, every other session) indefinitely.
    try:
        return subprocess.run(
            ["docker", *args],
            check=check,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Docker command timed out after {timeout}s: docker {' '.join(args[:2])} ..."
        ) from exc


def _keepalive_command() -> list[str]:
    return ["sh", "-c", "while true; do sleep 3600; done"]


def _sanitize_session_id(session_id: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", (session_id or "default").strip())
    normalized = normalized.strip(".-") or "default"
    return normalized[:48]


def _container_name_for_session(session_id: str) -> str:
    validated_session_id = validate_session_id(session_id)
    prefix = settings.docker_container_name.strip() or "deepanalyze-chat-exec"
    digest = hashlib.sha256(validated_session_id.encode("utf-8")).hexdigest()[:12]
    suffix = f"{_sanitize_session_id(validated_session_id)[:32]}-{digest}"
    return f"{prefix}-{suffix}"[:120]


def _container_exists(container_name: str) -> bool:
    completed = _run_docker_command(
        ["ps", "-a", "--filter", f"name=^{container_name}$", "--format", "{{.Names}}"],
        check=False,
    )
    return container_name in (completed.stdout or "").splitlines()


def _container_is_running(container_name: str) -> bool:
    completed = _run_docker_command(
        ["inspect", "-f", "{{.State.Running}}", container_name],
        check=False,
    )
    return (completed.returncode == 0) and (completed.stdout or "").strip().lower() == "true"


def _image_exists(image_name: str) -> bool:
    completed = _run_docker_command(
        ["image", "inspect", image_name],
        check=False,
        timeout=20,
    )
    return completed.returncode == 0


def _container_matches_session(
    container_name: str,
    session_id: str,
    session_workspace: Path,
) -> bool:
    completed = _run_docker_command(
        ["inspect", container_name],
        check=False,
        timeout=20,
    )
    if completed.returncode != 0:
        return False
    try:
        payload = json.loads(completed.stdout or "[]")[0]
        labels = payload.get("Config", {}).get("Labels", {}) or {}
        mounts = payload.get("Mounts", []) or []
    except (IndexError, TypeError, ValueError):
        return False
    if labels.get(MANAGED_LABEL_KEY) != "true" or labels.get(SESSION_LABEL_KEY) != session_id:
        return False
    expected_source = session_workspace.resolve()
    return any(
        mount.get("Destination") == settings.docker_workspace_dir
        and Path(str(mount.get("Source") or "")).resolve() == expected_source
        for mount in mounts
    )


def _touch_container(session_id: str, container_name: str, *, created_by_app: bool, started_by_app: bool) -> None:
    state = _SESSION_CONTAINERS.get(session_id)
    now = time.time()
    if state is None:
        _SESSION_CONTAINERS[session_id] = SessionContainerState(
            session_id=session_id,
            container_name=container_name,
            created_by_app=created_by_app,
            started_by_app=started_by_app,
            last_used_at=now,
        )
        return
    state.last_used_at = now
    state.created_by_app = state.created_by_app or created_by_app
    state.started_by_app = state.started_by_app or started_by_app


def _remove_container(container_name: str, *, remove: bool) -> None:
    if _container_is_running(container_name):
        _run_docker_command(["stop", container_name], check=False, timeout=20)
    if remove:
        _run_docker_command(["rm", "-f", container_name], check=False, timeout=20)


def _cleanup_idle_session_containers(now: float | None = None) -> None:
    if not settings.use_docker_execution:
        return

    ttl = max(0, settings.docker_session_idle_ttl_sec)
    if ttl <= 0:
        return

    now = now or time.time()
    expired_sessions = [
        session_id
        for session_id, state in _SESSION_CONTAINERS.items()
        if now - state.last_used_at >= ttl
    ]
    for session_id in expired_sessions:
        state = _SESSION_CONTAINERS.pop(session_id, None)
        if state is None:
            continue
        try:
            _remove_container(state.container_name, remove=state.created_by_app)
        except RuntimeError:
            # Best-effort reclamation; never let cleanup break the caller.
            continue


def cleanup_idle_containers() -> None:
    """Public entry point for the periodic idle-container reaper."""
    if not settings.use_docker_execution:
        return
    with _DOCKER_LOCK:
        _cleanup_idle_session_containers()


def remove_orphan_managed_containers() -> None:
    """Remove managed containers left behind by a previous backend process.

    Only runs when docker_stop_on_shutdown is enabled: it completes the same
    contract for backends that crashed before their shutdown hook could run.
    """
    if not settings.use_docker_execution or not settings.docker_stop_on_shutdown:
        return
    completed = _run_docker_command(
        [
            "ps",
            "-a",
            "--filter",
            f"label={MANAGED_LABEL_KEY}=true",
            "--format",
            "{{.Names}}",
        ],
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        return
    orphan_names = [name for name in (completed.stdout or "").split() if name]
    with _DOCKER_LOCK:
        tracked = {state.container_name for state in _SESSION_CONTAINERS.values()}
        for name in orphan_names:
            if name in tracked:
                continue
            try:
                _remove_container(name, remove=True)
            except RuntimeError:
                continue


def ensure_execution_backend_ready(session_id: str | None = None) -> None:
    if not settings.use_docker_execution or not session_id:
        return

    validated_session_id = validate_session_id(session_id)
    session_workspace = resolve_workspace_root(validated_session_id)
    container_name = _container_name_for_session(session_id)

    with _DOCKER_LOCK:
        _cleanup_idle_session_containers()

        if _container_is_running(container_name):
            if not _container_matches_session(
                container_name, validated_session_id, session_workspace
            ):
                raise RuntimeError("Existing execution container failed isolation validation")
            _touch_container(
                validated_session_id,
                container_name,
                created_by_app=True,
                started_by_app=False,
            )
            return

        if _container_exists(container_name):
            if not _container_matches_session(
                container_name, validated_session_id, session_workspace
            ):
                raise RuntimeError("Existing execution container failed isolation validation")
            _run_docker_command(["start", container_name])
            _touch_container(
                validated_session_id,
                container_name,
                created_by_app=True,
                started_by_app=True,
            )
            return

        if not _image_exists(settings.docker_image):
            raise RuntimeError(
                "Docker image not found. Build it first with "
                "`docker build -t deepanalyze-chat-exec:latest -f Dockerfile.exec .`"
            )

        docker_args = [
                "run",
                "-d",
                "--name",
                container_name,
                "--label",
                f"{MANAGED_LABEL_KEY}=true",
                "--label",
                f"{SESSION_LABEL_KEY}={validated_session_id}",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--network",
                settings.docker_network_mode or "none",
                "--memory",
                settings.docker_memory,
                "--cpus",
                str(settings.docker_cpus),
                "--pids-limit",
                str(settings.docker_pids_limit),
                "-v",
                f"{session_workspace}:{settings.docker_workspace_dir}:rw",
                "-w",
                settings.docker_workspace_dir,
        ]
        if settings.docker_user:
            docker_args.extend(["--user", settings.docker_user])
        if settings.docker_read_only:
            docker_args.append("--read-only")
        if settings.docker_tmpfs_size:
            docker_args.extend(
                ["--tmpfs", f"/tmp:rw,nosuid,nodev,size={settings.docker_tmpfs_size}"]
            )
        docker_args.extend([settings.docker_image, *_keepalive_command()])
        _run_docker_command(docker_args)
        _touch_container(
            validated_session_id,
            container_name,
            created_by_app=True,
            started_by_app=True,
        )


def shutdown_execution_backend() -> None:
    if not settings.use_docker_execution or not settings.docker_stop_on_shutdown:
        return

    with _DOCKER_LOCK:
        for session_id, state in list(_SESSION_CONTAINERS.items()):
            try:
                _remove_container(state.container_name, remove=state.created_by_app)
            except RuntimeError:
                pass
            _SESSION_CONTAINERS.pop(session_id, None)


def _resolve_container_workdir(workspace_dir: str, session_id: str) -> str:
    workspace_root = resolve_workspace_root(session_id)
    exec_dir = Path(workspace_dir).resolve()
    relative_dir = exec_dir.relative_to(workspace_root)
    if str(relative_dir) in {"", "."}:
        return settings.docker_workspace_dir
    return str(PurePosixPath(settings.docker_workspace_dir) / relative_dir.as_posix())


def execute_python_in_docker(
    script_path: str,
    workspace_dir: str,
    timeout_sec: int,
    session_id: str,
    cancel_event: threading.Event | None = None,
) -> str:
    ensure_execution_backend_ready(session_id)
    container_name = _container_name_for_session(session_id)
    container_workdir = _resolve_container_workdir(workspace_dir, session_id)
    script_name = Path(script_path).name

    try:
        process = subprocess.Popen(
            [
                "docker",
                "exec",
                "-e",
                "MPLBACKEND=Agg",
                "-e",
                "MPLCONFIGDIR=/tmp/matplotlib",
                "-e",
                "QT_QPA_PLATFORM=offscreen",
                "-e",
                "HOME=/tmp",
                "-w",
                container_workdir,
                container_name,
                settings.docker_python_bin,
                script_name,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        deadline = time.monotonic() + timeout_sec
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                cancelled = cancel_event is not None and cancel_event.is_set()
                timed_out = time.monotonic() >= deadline
                if not cancelled and not timed_out:
                    continue
                process.terminate()
                _run_docker_command(["stop", "-t", "1", container_name], check=False, timeout=10)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                if cancelled:
                    return "[Cancelled]: execution stopped by user"
                return f"[Timeout]: execution exceeded {timeout_sec} seconds"

        with _DOCKER_LOCK:
            _touch_container(
                session_id,
                container_name,
                created_by_app=False,
                started_by_app=False,
            )
        output = (stdout or "") + (stderr or "")
        if process.returncode:
            details = output.strip()
            suffix = f"\n{details}" if details else ""
            return f"[Error]: docker exec failed with exit code {process.returncode}{suffix}"
        return output
    except Exception as exc:
        return f"[Error]: {exc}"


def validate_execution_backend_configuration() -> None:
    execution_mode = settings.execution_mode.strip().lower()
    if execution_mode not in {"docker", "local"}:
        raise RuntimeError(f"Unsupported execution mode: {settings.execution_mode!r}")
    if not settings.use_docker_execution:
        if not settings.allow_unsafe_local_execution:
            raise RuntimeError(
                "Local execution is disabled. Set DEEPANALYZE_EXECUTION_MODE=docker "
                "or explicitly set DEEPANALYZE_ALLOW_UNSAFE_LOCAL_EXECUTION=true "
                "for trusted development."
            )
        return
    if shutil.which("docker") is None:
        raise RuntimeError("Docker CLI was not found")
    if not _image_exists(settings.docker_image):
        raise RuntimeError(
            f"Docker image {settings.docker_image!r} was not found. "
            "Build it with `docker build -t deepanalyze-chat-exec:latest -f Dockerfile.exec .`."
        )
