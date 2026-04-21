"""POST /generate -- SSE-streamed application package generation."""

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

from resumate.middleware.auth import get_current_user
from resumate.utils.sse import format_sse
from resumate.services.generation import generate_application_package
from resumate.config.settings import get_user_data_dir

logger = logging.getLogger("resumate")
router = APIRouter()

# Tasks that carry text content for the client.
_TEXT_TASKS = {"skills", "cover", "emails", "ats"}


class GenerateRequest(BaseModel):
    job_description: str
    profile_id: str | None = None


async def _iter_pipeline(jd_text: str, user_data_dir: Path) -> AsyncGenerator[tuple[str, Any], None]:
    """Bridge the synchronous RAG generator to an async generator."""
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
    """Stream generation results as server-sent events."""
    jd_text = request.job_description.strip()
    user_data_dir = get_user_data_dir(user["user_id"])

    async def event_stream():
        yield format_sse("status", "starting")
        try:
            async for event_name, payload in _iter_pipeline(jd_text, user_data_dir):
                if event_name == "progress":
                    yield format_sse("progress", payload)
                elif event_name == "token":
                    yield format_sse("token", json.dumps(payload))
                elif event_name in _TEXT_TASKS:
                    logger.info("task complete: %s (%d chars)", event_name, len(payload))
                    yield format_sse("task", json.dumps({"task": event_name, "content": payload}))
            yield format_sse("status", "done")
        except Exception as exc:
            logger.exception("generation error: %s", exc)
            yield format_sse("error", json.dumps({"message": str(exc)}))

    return StreamingResponse(event_stream(), media_type="text/event-stream")
