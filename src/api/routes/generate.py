"""POST /generate — SSE-streamed application package generation."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pathlib import Path
from pydantic import BaseModel

from api.auth import get_current_user
from api.sse import format_sse
from rag.generation.generator import generate_application_package
from rag.config.settings import get_user_data_dir

logger = logging.getLogger("api")
router = APIRouter()

# Tasks that carry text content for the client.
# The pipeline also yields ("_meta", dict) — skipped here; it's internal.
_TEXT_TASKS = {"skills", "cover", "emails", "ats"}


class GenerateRequest(BaseModel):
    job_description: str
    profile_id: str | None = None  # reserved for Phase 2 multi-profile support


async def _iter_pipeline(jd_text: str, user_data_dir: Path) -> AsyncGenerator[tuple[str, Any], None]:
    """Bridge the synchronous RAG generator to an async generator.

    ``generate_application_package`` blocks the calling thread on each Ollama
    call (20–60 s per task).  Running it directly on the event loop would stall
    all other requests.  Instead we push it onto a daemon thread and funnel
    yielded values back to the async world via an ``asyncio.Queue``.

    Sentinel ``None`` signals normal completion; an ``Exception`` instance
    signals an error and is re-raised on the async side.
    """
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[tuple[str, Any] | Exception | None] = asyncio.Queue()

    def _worker() -> None:
        try:
            for item in generate_application_package(
                jd_text, save_to_disk=False, progress=None, user_data_dir=user_data_dir
            ):
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    while True:
        item = await queue.get()
        if item is None:
            break
        if isinstance(item, Exception):
            raise item
        yield item  # type: ignore[misc]


@router.post("/generate")
async def generate(
    request: GenerateRequest,
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """Stream generation results as server-sent events.

    Event types emitted:
    - ``status``  — ``"starting"`` at open, ``"done"`` at completion
    - ``task``    — ``{"task": <name>, "content": <text>}`` per completed task
    - ``error``   — ``{"message": <str>}`` on any exception
    """
    jd_text = request.job_description.strip()
    user_data_dir = get_user_data_dir(user["user_id"])

    async def event_stream():
        yield format_sse("status", "starting")
        try:
            async for task_name, result in _iter_pipeline(jd_text, user_data_dir):
                if task_name not in _TEXT_TASKS:
                    continue
                logger.info("task complete: %s (%d chars)", task_name, len(result))
                yield format_sse("task", json.dumps({"task": task_name, "content": result}))
            yield format_sse("status", "done")
        except Exception as exc:
            logger.exception("generation error: %s", exc)
            yield format_sse("error", json.dumps({"message": str(exc)}))

    return StreamingResponse(event_stream(), media_type="text/event-stream")
