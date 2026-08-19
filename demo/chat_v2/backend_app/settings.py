from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


os.environ.setdefault("MPLBACKEND", "Agg")


def _load_demo_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int_env(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _get_float_env(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


_load_demo_env()


CHINESE_MATPLOTLIB_BOOTSTRAP = """
import matplotlib.pyplot as plt
plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False
"""


PREVIEWABLE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".pdf",
    ".txt",
    ".doc",
    ".docx",
    ".csv",
    ".xlsx",
}


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


@dataclass(frozen=True)
class Settings:
    api_base: str = os.getenv("DEEPANALYZE_API_BASE", "http://localhost:8000/v1")
    model_path: str = os.getenv("DEEPANALYZE_MODEL_PATH", "DeepAnalyze-8B")
    workspace_base_dir: str = os.getenv(
        "DEEPANALYZE_WORKSPACE_BASE",
        str(Path(__file__).resolve().parent.parent / "workspace"),
    )
    http_server_host: str = os.getenv("DEEPANALYZE_FILE_SERVER_HOST", "localhost")
    http_server_port: int = int(os.getenv("DEEPANALYZE_FILE_SERVER_PORT", "8100"))
    backend_host: str = os.getenv("DEEPANALYZE_BACKEND_HOST", "0.0.0.0")
    backend_port: int = int(os.getenv("DEEPANALYZE_BACKEND_PORT", "8200"))
    execution_mode: str = os.getenv("DEEPANALYZE_EXECUTION_MODE", "docker")
    allow_unsafe_local_execution: bool = _get_bool_env(
        "DEEPANALYZE_ALLOW_UNSAFE_LOCAL_EXECUTION",
        False,
    )
    execution_timeout_sec: int = _get_int_env(
        "DEEPANALYZE_EXECUTION_TIMEOUT_SEC", 120, minimum=1
    )
    docker_image: str = os.getenv(
        "DEEPANALYZE_DOCKER_IMAGE", "deepanalyze-chat-exec:latest"
    )
    docker_auto_build: bool = _get_bool_env(
        "DEEPANALYZE_DOCKER_AUTO_BUILD",
        True,
    )
    docker_container_name: str = os.getenv(
        "DEEPANALYZE_DOCKER_CONTAINER_NAME",
        "deepanalyze-chat-exec",
    )
    docker_session_idle_ttl_sec: int = int(
        os.getenv("DEEPANALYZE_DOCKER_SESSION_IDLE_TTL_SEC", "1800")
    )
    docker_workspace_dir: str = os.getenv("DEEPANALYZE_DOCKER_WORKSPACE_DIR", "/workspace")
    docker_python_bin: str = os.getenv("DEEPANALYZE_DOCKER_PYTHON_BIN", "python")
    docker_network_mode: str = os.getenv("DEEPANALYZE_DOCKER_NETWORK_MODE", "none").strip()
    docker_memory: str = os.getenv("DEEPANALYZE_DOCKER_MEMORY", "1g").strip()
    docker_cpus: float = _get_float_env("DEEPANALYZE_DOCKER_CPUS", 1.0, minimum=0.1)
    docker_pids_limit: int = _get_int_env(
        "DEEPANALYZE_DOCKER_PIDS_LIMIT", 256, minimum=16
    )
    docker_user: str = os.getenv("DEEPANALYZE_DOCKER_USER", "1000:1000").strip()
    docker_read_only: bool = _get_bool_env("DEEPANALYZE_DOCKER_READ_ONLY", True)
    docker_tmpfs_size: str = os.getenv(
        "DEEPANALYZE_DOCKER_TMPFS_SIZE", "256m"
    ).strip()
    docker_stop_on_shutdown: bool = _get_bool_env(
        "DEEPANALYZE_DOCKER_STOP_ON_SHUTDOWN",
        True,
    )
    pdf_cjk_mainfont: str = os.getenv("DEEPANALYZE_PDF_CJK_MAINFONT", "").strip()
    pdf_auto_download_pandoc: bool = _get_bool_env(
        "DEEPANALYZE_PDF_AUTO_DOWNLOAD_PANDOC",
        True,
    )
    pdf_pandoc_cache_dir: str = os.getenv(
        "DEEPANALYZE_PDF_PANDOC_CACHE_DIR",
        "",
    ).strip()
    upload_max_file_bytes: int = _get_int_env(
        "DEEPANALYZE_UPLOAD_MAX_FILE_BYTES", 100 * 1024 * 1024, minimum=1
    )
    workspace_max_bytes: int = _get_int_env(
        "DEEPANALYZE_WORKSPACE_MAX_BYTES", 1024 * 1024 * 1024, minimum=1
    )
    workspace_max_files: int = _get_int_env(
        "DEEPANALYZE_WORKSPACE_MAX_FILES", 500, minimum=1
    )
    upload_chunk_bytes: int = _get_int_env(
        "DEEPANALYZE_UPLOAD_CHUNK_BYTES", 1024 * 1024, minimum=64 * 1024
    )
    chat_max_rounds: int = _get_int_env("DEEPANALYZE_CHAT_MAX_ROUNDS", 12, minimum=1)
    chat_max_code_executions: int = _get_int_env(
        "DEEPANALYZE_CHAT_MAX_CODE_EXECUTIONS", 8, minimum=1
    )
    chat_max_duration_sec: int = _get_int_env(
        "DEEPANALYZE_CHAT_MAX_DURATION_SEC", 900, minimum=1
    )
    chat_max_response_chars: int = _get_int_env(
        "DEEPANALYZE_CHAT_MAX_RESPONSE_CHARS", 1_000_000, minimum=1024
    )
    model_stream_read_timeout_sec: int = _get_int_env(
        "DEEPANALYZE_MODEL_STREAM_READ_TIMEOUT_SEC", 60, minimum=5
    )
    execution_output_max_chars: int = _get_int_env(
        "DEEPANALYZE_EXECUTION_OUTPUT_MAX_CHARS", 32768, minimum=1024
    )
    enable_external_proxy: bool = _get_bool_env(
        "DEEPANALYZE_ENABLE_EXTERNAL_PROXY",
        False,
    )

    @property
    def file_server_base(self) -> str:
        return f"http://{self.http_server_host}:{self.http_server_port}"

    @property
    def use_docker_execution(self) -> bool:
        return self.execution_mode.strip().lower() == "docker"


settings = Settings()
