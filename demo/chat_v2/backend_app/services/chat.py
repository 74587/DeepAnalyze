from __future__ import annotations

import json
import logging
import re
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import httpx
import openai

from .execution import build_file_block
from .execution_service import execute_managed_code
from .docker_executor import ensure_execution_backend_ready
from .action_protocol import (
    ProtocolValidationError,
    contains_completed_action,
    normalize_model_output,
)
from .workspace import (
    collect_file_info,
    get_session_workspace,
    register_generated_paths,
    resolve_workspace_path,
    uniquify_path,
    validate_session_id,
)
from ..settings import CHINESE_MATPLOTLIB_BOOTSTRAP, settings


client = openai.OpenAI(base_url=settings.api_base, api_key="dummy")
logger = logging.getLogger(__name__)
_STOP_EVENTS: dict[str, threading.Event] = {}
_STOP_EVENTS_LOCK = threading.Lock()
_SESSION_RUN_LOCKS: dict[str, threading.Lock] = {}
_SESSION_RUN_LOCKS_LOCK = threading.Lock()
HEYWHALE_API_BASE = (
    "https://www.heywhale.com/api/model/services/691d42c36c6dda33df0bf645/app/v1"
)
HEYWHALE_BACKUP_CHAT_COMPLETIONS_URL = (
    "https://www.heywhale.com/api/model/services/69b7c9d028cbfe8349df5924/app/v1/chat/completions"
)
HEYWHALE_STOP_SEQUENCES = ["</Code>", "</Answer>"]
EXECUTE_RESULT_PREFIX = "# Execute Result\n"
FIXED_MODEL_NAME = "DeepAnalyze-8B"
_FENCE_WITH_INFO_RE = re.compile(r"```[ \t]*[\w.+-]*[ \t]*\r?\n(.*?)```", re.DOTALL)
_FENCE_INLINE_RE = re.compile(r"```(?:python)?(.*?)```", re.DOTALL | re.IGNORECASE)
_ACTION_TAG_AT_START_RE = re.compile(
    r"^\s*</?[A-Za-z][^>]*>",
)
@dataclass(frozen=True)
class ChatRuntimeConfig:
    provider: str = "local"
    temperature: float = 0.4
    model: str = settings.model_path
    api_key: str = ""
    api_base: str = ""


def _is_deepanalyze_model(model_name: str) -> bool:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return False
    return bool(re.search(r"deep[\s\-_]*analyze", normalized))


def _build_execution_feedback_message(
    runtime_config: ChatRuntimeConfig,
    execution_output: str,
) -> dict[str, str]:
    if not _is_deepanalyze_model(runtime_config.model):
        return {
            "role": "user",
            "content": f"{EXECUTE_RESULT_PREFIX}{execution_output}",
        }
    return {"role": "execute", "content": execution_output}


def _get_or_create_stop_event(session_id: str) -> threading.Event:
    sid = validate_session_id(session_id)
    with _STOP_EVENTS_LOCK:
        event = _STOP_EVENTS.get(sid)
        if event is None:
            event = threading.Event()
            _STOP_EVENTS[sid] = event
        return event


def request_stop(session_id: str) -> None:
    _get_or_create_stop_event(session_id).set()


def get_session_stop_event(session_id: str) -> threading.Event:
    return _get_or_create_stop_event(session_id)


def _get_or_create_session_run_lock(session_id: str) -> threading.Lock:
    sid = validate_session_id(session_id)
    with _SESSION_RUN_LOCKS_LOCK:
        lock = _SESSION_RUN_LOCKS.get(sid)
        if lock is None:
            lock = threading.Lock()
            _SESSION_RUN_LOCKS[sid] = lock
        return lock


def try_acquire_session_run(session_id: str) -> threading.Lock | None:
    lock = _get_or_create_session_run_lock(session_id)
    return lock if lock.acquire(blocking=False) else None


def release_session_run(session_id: str, lock: threading.Lock) -> None:
    # Do NOT clear the stop event here: a stop request that lands in the gap
    # between run completion and release would be silently swallowed. The event
    # is cleared at the start of each new run instead.
    lock.release()


def _execution_status_block(kind: str, message: str) -> str:
    logger.warning("analysis_status kind=%s message=%s", kind, message)
    return f"\n<Execute>\n[{kind}]: {message}\n</Execute>\n"


def _normalize_temperature(value: Any) -> float:
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        return 0.4
    return max(0.0, min(2.0, temperature))


def _prefix_initial_analyze_tag(content: str) -> str:
    """首轮输出未以已知动作标签开头时，只补齐 Analyze 开标签。"""
    raw = content or ""
    if not raw.strip() or _ACTION_TAG_AT_START_RE.match(raw):
        return raw
    leading_length = len(raw) - len(raw.lstrip())
    return f"{raw[:leading_length]}<Analyze>{raw[leading_length:]}"


def build_chat_runtime_config(payload: dict[str, Any] | None) -> ChatRuntimeConfig:
    body = payload or {}
    provider = str(body.get("provider") or "local").strip().lower() or "local"
    if provider not in {"local", "heywhale", "custom"}:
        provider = "local"

    api_base = str(body.get("api_base") or "").strip()
    if provider == "heywhale" and not api_base:
        api_base = HEYWHALE_API_BASE
    if provider == "custom" and not api_base:
        raise ValueError("Custom API base is required")

    if provider in {"local", "heywhale"}:
        model = FIXED_MODEL_NAME
    else:
        model = str(body.get("model") or FIXED_MODEL_NAME).strip() or FIXED_MODEL_NAME
    api_key = str(body.get("api_key") or "").strip()
    if provider == "heywhale" and not api_key:
        raise ValueError("HeyWhale API key is required")

    return ChatRuntimeConfig(
        provider=provider,
        temperature=_normalize_temperature(body.get("temperature")),
        model=model,
        api_key=api_key,
        api_base=api_base,
    )


def _iter_local_stream(
    conversation: list[dict[str, Any]],
    runtime_config: ChatRuntimeConfig,
):
    response = client.with_options(
        timeout=settings.model_stream_read_timeout_sec
    ).chat.completions.create(
        model=runtime_config.model,
        messages=conversation,
        temperature=runtime_config.temperature,
        stream=True,
        extra_body={
            "add_generation_prompt": False,
            "stop_token_ids": [151676, 151645],
            "max_new_tokens": 32768,
        },
    )
    try:
        for chunk in response:
            yield chunk.choices[0].delta.content if chunk.choices else None, chunk
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def _iter_heywhale_stream(
    conversation: list[dict[str, Any]],
    runtime_config: ChatRuntimeConfig,
):
    if not runtime_config.api_key:
        raise ValueError("HeyWhale API key is required")

    request_body = {
        "messages": conversation,
        "temperature": runtime_config.temperature,
        "stream": True,
        "stop": HEYWHALE_STOP_SEQUENCES,
    }

    primary_url = f"{runtime_config.api_base.rstrip('/')}/chat/completions"
    request_urls = [primary_url]
    if runtime_config.api_base.rstrip("/") == HEYWHALE_API_BASE.rstrip("/"):
        request_urls.append(HEYWHALE_BACKUP_CHAT_COMPLETIONS_URL)

    timeout = httpx.Timeout(settings.model_stream_read_timeout_sec, connect=10)
    with httpx.Client(timeout=timeout) as http_client:
        for idx, request_url in enumerate(request_urls):
            has_stream_output = False
            streamed_content = ""
            try:
                with http_client.stream(
                    "POST",
                    request_url,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {runtime_config.api_key}",
                    },
                    json=request_body,
                ) as response:
                    response.raise_for_status()
                    for raw_line in response.iter_lines():
                        if not raw_line:
                            continue
                        line = raw_line.strip()
                        if not line:
                            continue
                        if line.startswith("data:"):
                            line = line[5:].strip()
                        if line == "[DONE]":
                            break
                        try:
                            payload = json.loads(line)
                        except Exception:
                            continue
                        has_stream_output = True
                        choice = (payload.get("choices") or [{}])[0]
                        delta = (choice.get("delta") or {}).get("content")
                        finish_reason = choice.get("finish_reason")
                        if delta:
                            streamed_content += delta
                        yield delta, {"choices": [{"finish_reason": finish_reason}]}
                        if finish_reason == "stop":
                            if (
                                streamed_content.rfind("<Code>")
                                > streamed_content.rfind("</Code>")
                            ):
                                yield "</Code>", {"choices": [{"finish_reason": None}]}
                            elif (
                                streamed_content.rfind("<Answer>")
                                > streamed_content.rfind("</Answer>")
                            ):
                                yield "</Answer>", {"choices": [{"finish_reason": None}]}
                return
            except httpx.HTTPError:
                if has_stream_output or idx >= len(request_urls) - 1:
                    raise
                continue


def _iter_custom_stream(
    conversation: list[dict[str, Any]],
    runtime_config: ChatRuntimeConfig,
):
    request_body = {
        "model": runtime_config.model,
        "messages": conversation,
        "temperature": runtime_config.temperature,
        "stream": True,
    }

    headers = {"Content-Type": "application/json"}
    if runtime_config.api_key:
        headers["Authorization"] = f"Bearer {runtime_config.api_key}"

    timeout = httpx.Timeout(settings.model_stream_read_timeout_sec, connect=10)
    with httpx.Client(timeout=timeout) as http_client:
        with http_client.stream(
            "POST",
            f"{runtime_config.api_base.rstrip('/')}/chat/completions",
            headers=headers,
            json=request_body,
        ) as response:
            response.raise_for_status()
            for raw_line in response.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                choice = (payload.get("choices") or [{}])[0]
                delta = (choice.get("delta") or {}).get("content")
                finish_reason = choice.get("finish_reason")
                yield delta, {"choices": [{"finish_reason": finish_reason}]}


def _resolve_workspace_selection(
    workspace: Iterable[str] | None,
    workspace_dir: str,
) -> list[Path]:
    workspace_root = Path(workspace_dir).resolve()
    resolved_paths: list[Path] = []
    for item in workspace or []:
        candidate = Path(item)
        if candidate.is_absolute():
            candidate = candidate.resolve()
            if candidate != workspace_root and workspace_root not in candidate.parents:
                continue
        else:
            try:
                candidate = resolve_workspace_path(
                    workspace_root.name,
                    str(candidate),
                )
            except Exception:
                continue
        if candidate.exists() and candidate.is_file():
            resolved_paths.append(candidate)
    return resolved_paths


def _build_user_prompt(
    messages: list[dict[str, Any]],
    workspace: list[str],
    workspace_dir: str,
    *,
    use_all_files_when_empty: bool,
) -> None:
    if not messages or messages[-1].get("role") != "user":
        return

    user_message = str(messages[-1].get("content") or "")
    selected_paths = _resolve_workspace_selection(workspace, workspace_dir)
    file_source: list[Path] | str = selected_paths
    if not selected_paths and use_all_files_when_empty:
        file_source = workspace_dir
    file_info = collect_file_info(file_source)
    if file_info:
        messages[-1]["content"] = f"# Instruction\n{user_message}\n\n# Data\n{file_info}"
    else:
        messages[-1]["content"] = f"# Instruction\n{user_message}"


def _extract_code_to_execute(code_content: str) -> str | None:
    if not code_content:
        return None
    # Prefer a fenced block whose opening line carries an optional single-token
    # info string (```python / ```py / ```Python3 ...); fall back to the legacy
    # inline form so bare ``` ... ``` fences keep working.
    md_match = _FENCE_WITH_INFO_RE.search(code_content) or _FENCE_INLINE_RE.search(
        code_content
    )
    code_str = md_match.group(1).strip() if md_match else code_content
    if re.search(r"(^|\W)(plt\.|matplotlib|sns\.|seaborn)", code_str, re.IGNORECASE):
        return CHINESE_MATPLOTLIB_BOOTSTRAP + "\n" + code_str
    return code_str


def _save_answer_markdown_report(
    answer_content: str,
    workspace_dir: str,
    session_id: str,
) -> Path | None:
    if not answer_content:
        return None

    workspace_root = Path(workspace_dir).resolve()
    generated_root = (workspace_root / "generated").resolve()
    generated_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = uniquify_path(generated_root / f"Answer_Report_{timestamp}.md")
    report_path.write_text(answer_content.rstrip() + "\n", encoding="utf-8")

    rel_path = report_path.relative_to(workspace_root).as_posix()
    register_generated_paths(session_id, [rel_path])
    return report_path


def _prewarm_execution_backend(session_id: str) -> None:
    """Allocate/reuse the session container while the model is still generating,
    so the first <Code> block does not pay the container start-up cost."""
    try:
        ensure_execution_backend_ready(session_id)
    except Exception as exc:  # pragma: no cover - best-effort warm-up
        logger.warning("container prewarm failed for %s: %s", session_id, exc)


def bot_stream(
    messages: list[dict[str, Any]],
    workspace: list[str] | None,
    session_id: str = "default",
    runtime_config: ChatRuntimeConfig | None = None,
):
    runtime_config = runtime_config or ChatRuntimeConfig()
    session_id = validate_session_id(session_id)
    session_lock = try_acquire_session_run(session_id)
    if session_lock is None:
        yield _execution_status_block("Session Busy", "another analysis is already running")
        return

    stop_event = _get_or_create_stop_event(session_id)
    try:
        conversation = deepcopy(messages or [])
        is_initial_conversation = not any(
            message.get("role") == "assistant" for message in conversation
        )
        workspace_paths = list(workspace or [])
        workspace_dir = get_session_workspace(session_id)
        Path(workspace_dir, "generated").mkdir(parents=True, exist_ok=True)
        if settings.use_docker_execution:
            threading.Thread(
                target=_prewarm_execution_backend,
                args=(session_id,),
                daemon=True,
            ).start()

        if conversation and conversation[0].get("role") == "assistant":
            conversation = conversation[1:]

        _build_user_prompt(
            conversation,
            workspace_paths,
            workspace_dir,
            use_all_files_when_empty=workspace is None,
        )
        initial_workspace = {
            path.resolve() for path in Path(workspace_dir).rglob("*") if path.is_file()
        }
        finished = False
        round_count = 0
        code_execution_count = 0
        started_at = time.monotonic()
        stop_event.clear()
        while not finished:
            if stop_event.is_set():
                break
            if time.monotonic() - started_at >= settings.chat_max_duration_sec:
                yield _execution_status_block(
                    "Budget Exceeded",
                    f"analysis exceeded {settings.chat_max_duration_sec} seconds",
                )
                break
            if round_count >= settings.chat_max_rounds:
                yield _execution_status_block(
                    "Budget Exceeded",
                    f"analysis exceeded {settings.chat_max_rounds} model rounds",
                )
                break
            round_count += 1

            cur_res = ""
            stream_iter = (
                _iter_heywhale_stream(conversation, runtime_config)
                if runtime_config.provider == "heywhale"
                else (
                    _iter_custom_stream(conversation, runtime_config)
                    if runtime_config.provider == "custom"
                    else _iter_local_stream(conversation, runtime_config)
                )
            )
            try:
                for delta, chunk in stream_iter:
                    if stop_event.is_set():
                        break
                    if time.monotonic() - started_at >= settings.chat_max_duration_sec:
                        yield _execution_status_block(
                            "Budget Exceeded",
                            f"analysis exceeded {settings.chat_max_duration_sec} seconds",
                        )
                        finished = True
                        break
                    if delta is not None:
                        cur_res += delta
                        if len(cur_res) > settings.chat_max_response_chars:
                            yield _execution_status_block(
                                "Budget Exceeded",
                                "model response exceeded the configured size limit",
                            )
                            finished = True
                            break
                    if contains_completed_action(cur_res, "Answer"):
                        break
            except (httpx.HTTPError, openai.OpenAIError) as exc:
                yield _execution_status_block("Model Error", str(exc))
                return

            if stop_event.is_set() or finished:
                break

            if is_initial_conversation and round_count == 1:
                cur_res = _prefix_initial_analyze_tag(cur_res)

            try:
                normalized_res, actions = normalize_model_output(cur_res)
            except ProtocolValidationError as exc:
                yield _execution_status_block("Protocol Error", str(exc))
                break
            if normalized_res != cur_res.strip():
                logger.info("normalized model action format for session %s", session_id)
            yield normalized_res
            cur_res = normalized_res

            terminal_action = actions[-1]
            if terminal_action.tag == "Answer":
                report_path = _save_answer_markdown_report(
                    terminal_action.body,
                    workspace_dir,
                    session_id,
                )
                if report_path is not None:
                    file_block = build_file_block([report_path], workspace_dir, session_id)
                    if file_block:
                        yield file_block
                finished = True
                continue

            if code_execution_count >= settings.chat_max_code_executions:
                yield _execution_status_block(
                    "Budget Exceeded",
                    f"analysis exceeded {settings.chat_max_code_executions} code executions",
                )
                break
            code_execution_count += 1
            conversation.append({"role": "assistant", "content": cur_res})
            code_str = _extract_code_to_execute(terminal_action.body)
            if not code_str:
                yield _execution_status_block("Protocol Error", "empty executable code")
                break

            remaining_seconds = max(
                1,
                settings.chat_max_duration_sec - int(time.monotonic() - started_at),
            )
            outcome = execute_managed_code(
                code_str,
                session_id,
                source="agent",
                timeout_sec=min(settings.execution_timeout_sec, remaining_seconds),
                cancel_event=stop_event,
            )
            yield outcome.execution_content

            conversation.append(
                _build_execution_feedback_message(runtime_config, outcome.result)
            )
            if stop_event.is_set():
                break

            current_files = {
                path.resolve() for path in Path(workspace_dir).rglob("*") if path.is_file()
            }
            new_files = [str(path) for path in current_files - initial_workspace]
            if new_files:
                workspace_paths.extend(new_files)
                initial_workspace.update(Path(path).resolve() for path in new_files)
    except GeneratorExit:
        # The client disconnected mid-stream; make sure the analysis loop and any
        # queued sandbox execution stop instead of burning the remaining budget.
        stop_event.set()
        raise
    finally:
        release_session_run(session_id, session_lock)
