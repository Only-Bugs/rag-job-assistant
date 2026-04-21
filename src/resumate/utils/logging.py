"""Logging helpers and timing instrumentation utilities."""

from __future__ import annotations

import json
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
import threading
from time import perf_counter
from typing import Any, Callable, Iterator, Mapping, TypeVar, TypedDict

logger = logging.getLogger("resumate")

F = TypeVar("F", bound=Callable[..., Any])
_REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="-")
_LOG_PATH = Path(__file__).resolve().parents[3] / "logs" / "runtime.log"
_PERFORMANCE_LOG_PATH = Path(__file__).resolve().parents[3] / "logs" / "performance.json"
_performance_json_lock = threading.Lock()


class PerformanceLog(TypedDict):
    """JSON schema for lines written to ``logs/performance.json`` (JSON Lines)."""

    timestamp: str
    task_name: str
    stage: str
    ttft_ms: float | None
    total_ms: float
    status: str


def log_performance_json(data: dict[str, Any]) -> None:
    """Append one JSON object per line to ``logs/performance.json`` (thread-safe)."""
    line_obj = dict(data)
    if "timestamp" not in line_obj:
        line_obj["timestamp"] = datetime.now(timezone.utc).isoformat()
    _PERFORMANCE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(line_obj, ensure_ascii=False) + "\n"
    with _performance_json_lock:
        with _PERFORMANCE_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)


_COLOR = {
    "OK": "\033[92m",
    "WARN": "\033[93m",
    "CHECK RUNTIME ERR": "\033[91m",
    "reset": "\033[0m",
}
_TAG_WIDTH = 22
_REQ_WIDTH = 10
_JOB_WIDTH = 28
_TIME_WIDTH = 11
_MSG_WIDTH = 84


def _preview_args(args: tuple[Any, ...], kwargs: dict[str, Any], limit: int = 80) -> str:
    """Build a compact argument preview for terminal logs."""
    parts: list[str] = []
    if args:
        parts.append(", ".join(repr(arg) for arg in args))
    if kwargs:
        parts.append(", ".join(f"{key}={value!r}" for key, value in kwargs.items()))

    preview = ", ".join(parts)
    if len(preview) > limit:
        return f"{preview[: limit - 3]}..."
    return preview


def set_request_id(request_id: str) -> None:
    """Set a request identifier for correlated timing lines."""
    _REQUEST_ID.set(request_id)


def get_request_id() -> str:
    """Get the current request identifier."""
    return _REQUEST_ID.get()


def _format_metadata(metadata: Mapping[str, Any] | None) -> str:
    if not metadata:
        return ""
    normalized = ", ".join(f"{key}={value!r}" for key, value in sorted(metadata.items()))
    return f" | {normalized}" if normalized else ""


def _status_for(elapsed_ms: float, success: bool) -> str:
    if not success:
        return "CHECK RUNTIME ERR"
    if elapsed_ms > 120_000:
        return "WARN"
    return "OK"


def _truncate(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return value[: width - 3] + "..."


def _format_table_line(tag: str, req_id: str, job: str, duration: str, message: str = "") -> str:
    req = _truncate(req_id, _REQ_WIDTH - 1)
    job_name = _truncate(job, _JOB_WIDTH - 1)
    dur = _truncate(duration, _TIME_WIDTH - 1)
    msg = _truncate(message, _MSG_WIDTH)
    return (
        f"[{tag}]".ljust(_TAG_WIDTH)
        + req.ljust(_REQ_WIDTH)
        + "  "
        + job_name.ljust(_JOB_WIDTH)
        + "  "
        + dur.ljust(_TIME_WIDTH)
        + "  "
        + msg
    )


def _emit(line: str, tag: str = "OK") -> None:
    """Emit a line to terminal and append plain text to runtime log file."""
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"{line}\n")
    if sys.stdout.isatty():
        plain_tag = f"[{tag}]"
        color = _COLOR.get(tag, _COLOR["OK"])
        if line.startswith(plain_tag):
            neutral = line[len(plain_tag) :]
            print(f"{color}{plain_tag}{_COLOR['reset']}{neutral}")
        else:
            print(line)


@contextmanager
def _live_timer(job: str) -> Iterator[None]:
    """Display an in-place elapsed timer while a job is active (terminal only)."""
    if not sys.stdout.isatty():
        yield
        return

    request_id = get_request_id()
    start = perf_counter()
    stop_event = threading.Event()

    def _render() -> None:
        while not stop_event.is_set():
            elapsed_ms = (perf_counter() - start) * 1000
            line = _format_table_line("OK", request_id, job, f"{elapsed_ms:.0f}ms", " RUNNING")
            print(f"\r{line}", end="", flush=True)
            stop_event.wait(0.2)
        print("\r" + " " * 160 + "\r", end="", flush=True)

    thread = threading.Thread(target=_render, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=0.5)


def log_call(
    func_name: str,
    elapsed_ms: float,
    args_preview: str = "",
    success: bool = True,
    metadata: Mapping[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Write structured timing lines to terminal + runtime log file."""
    tag = _status_for(elapsed_ms, success)
    request_id = get_request_id()
    args_part = f"args=({args_preview})" if args_preview else ""
    error_part = f"error={error!r}" if error else ""
    metadata_part = _format_metadata(metadata)
    message_parts = [p for p in [args_part, metadata_part.strip(" |"), error_part] if p]
    message = " | ".join(message_parts)
    line = _format_table_line(tag, request_id, func_name, f"{elapsed_ms:.2f}ms", message)
    _emit(line, tag=tag)


def log_run_start(job: str, args_preview: str = "") -> None:
    """Log a clearly marked run start event."""
    request_id = get_request_id()
    message = f" RUN START =============================== | args=({args_preview})" if args_preview else "RUN START ================================="
    line = _format_table_line("OK", request_id, job, "-", message)
    _emit(line, tag="OK")


def log_run_end(job: str, elapsed_ms: float, success: bool = True, error: str | None = None) -> None:
    """Log a clearly marked run end event."""
    request_id = get_request_id()
    tag = _status_for(elapsed_ms, success)
    message = " RUN END =================================" if success else f" RUN END | error={error!r} ================================="
    line = _format_table_line(tag, request_id, job, f"{elapsed_ms:.2f}ms", message)
    _emit(line, tag=tag)


def timed(func: F) -> F:
    """Decorator that logs function call timing and terminal status."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = perf_counter()
        args_preview = _preview_args(args, kwargs)
        with _live_timer(func.__name__):
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                elapsed_ms = (perf_counter() - start) * 1000
                log_call(func.__name__, elapsed_ms, args_preview=args_preview, success=False, error=str(exc))
                raise

        elapsed_ms = (perf_counter() - start) * 1000
        log_call(func.__name__, elapsed_ms, args_preview=args_preview, success=True)
        return result

    return wrapper  # type: ignore[return-value]


def timed_call(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Wrap-and-call helper for timing without decorator syntax."""
    return timed(func)(*args, **kwargs)

@contextmanager
def timed_block(name: str, metadata: Mapping[str, Any] | None = None) -> Iterator[None]:
    """Context manager to record elapsed time for named workflow steps."""
    start = perf_counter()
    with _live_timer(name):
        try:
            yield
        except Exception as exc:
            elapsed_ms = (perf_counter() - start) * 1000
            log_call(name, elapsed_ms, success=False, metadata=metadata, error=str(exc))
            raise
    elapsed_ms = (perf_counter() - start) * 1000
    log_call(name, elapsed_ms, success=True, metadata=metadata)


__all__ = [
    "logger",
    "log_call",
    "log_run_start",
    "log_run_end",
    "timed",
    "timed_call",
    "timed_block",
    "set_request_id",
    "get_request_id",
    "PerformanceLog",
    "log_performance_json",
]
