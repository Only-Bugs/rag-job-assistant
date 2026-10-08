"""POST /generate -- SSE-streamed application package generation."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pathlib import Path
from pydantic import BaseModel

from resumate.middleware.auth import get_current_user
from resumate.utils.sse import format_sse
from resumate.services.generation import generate_application_package
from resumate.config.settings import get_user_data_dir

logger = logging.getLogger("resumate")
router = APIRouter()

# Tasks that carry text content for the client.
_TEXT_TASKS = {"skills", "cover", "emails", "ats"}

# Active streams → cancel flags. Keyed by req_id.
_active_streams: dict[str, threading.Event] = {}
_active_lock = threading.Lock()


class GenerateRequest(BaseModel):
    job_description: str
    profile_id: str | None = None
    # Skip the out-of-domain guard ("Generate anyway").
    force: bool = False


class CancelRequest(BaseModel):
    req_id: str


async def _iter_pipeline(
    jd_text: str,
    user_data_dir: Path,
    cancel_event: threading.Event,
    force: bool = False,
) -> AsyncGenerator[tuple[str, Any], None]:
    """Bridge the synchronous RAG generator to an async generator."""
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[tuple[str, Any] | Exception | None] = asyncio.Queue()

    def _worker() -> None:
        gen = None
        try:
            gen = generate_application_package(
                jd_text, save_to_disk=False, progress=None, user_data_dir=user_data_dir, force=force
            )
            for item in gen:
                if cancel_event.is_set():
                    break
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            # Closing the generator closes the in-flight Ollama HTTP stream, which
            # stops generation server-side while keeping the model loaded.
            if gen is not None:
                gen.close()
            loop.call_soon_threadsafe(queue.put_nowait, None)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    while True:
        if cancel_event.is_set():
            break
        try:
            item = await asyncio.wait_for(queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
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
    """Stream generation results as server-sent events."""
    jd_text = request.job_description.strip()
    user_data_dir = get_user_data_dir(user["user_id"])

    req_id = uuid.uuid4().hex[:12]
    cancel_event = threading.Event()
    with _active_lock:
        _active_streams[req_id] = cancel_event

    async def event_stream():
        try:
            yield format_sse("stream", json.dumps({"req_id": req_id}))
            yield format_sse("status", "starting")
            try:
                blocked = False
                async for event_name, payload in _iter_pipeline(jd_text, user_data_dir, cancel_event, request.force):
                    if event_name == "progress":
                        yield format_sse("progress", payload)
                    elif event_name == "token":
                        yield format_sse("token", json.dumps(payload))
                    elif event_name == "blocked":
                        blocked = True
                        yield format_sse("blocked", json.dumps(payload))
                    elif event_name in _TEXT_TASKS:
                        logger.info("task complete: %s (%d chars)", event_name, len(payload))
                        yield format_sse("task", json.dumps({"task": event_name, "content": payload}))
                if cancel_event.is_set():
                    logger.info("stream cancelled: %s", req_id)
                    yield format_sse("cancelled", json.dumps({"req_id": req_id}))
                elif blocked:
                    yield format_sse("status", "blocked")
                else:
                    yield format_sse("status", "done")
            except Exception as exc:
                logger.exception("generation error: %s", exc)
                yield format_sse("error", json.dumps({"message": str(exc)}))
        finally:
            with _active_lock:
                _active_streams.pop(req_id, None)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/generate/cancel")
async def cancel_generate(
    request: CancelRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """Signal an in-flight generation stream to stop.

    The worker closes its Ollama stream at the next token. The model is not
    unloaded, so the next Generate starts warm instead of paying a cold load."""
    with _active_lock:
        event = _active_streams.pop(request.req_id, None)
    if event is None:
        raise HTTPException(status_code=404, detail="req_id not found or already finished")
    event.set()
    logger.info("cancel requested: %s", request.req_id)
    return {"status": "cancelled", "req_id": request.req_id}
