"""Tests for POST /generate SSE endpoint."""

from __future__ import annotations

import json
from unittest.mock import patch


def _fake_generator(jd_text, save_to_disk=False, progress=None, user_data_dir=None):
    """Yield fake task results mimicking the real pipeline."""
    for task in ("skills", "cover", "emails", "ats"):
        yield task, f"Fake {task} content"


def _parse_sse(text: str) -> list[dict]:
    """Parse raw SSE text into a list of {event, data} dicts."""
    events = []
    current: dict = {}
    for line in text.splitlines():
        if line.startswith("event: "):
            current["event"] = line[7:]
        elif line.startswith("data: "):
            current["data"] = line[6:]
        elif line == "" and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events


def test_generate_sse_stream(client):
    """Mocked pipeline should produce status + 4 task events + done."""
    with patch(
        "resumate.routes.generate.generate_application_package",
        side_effect=_fake_generator,
    ):
        resp = client.post(
            "/generate",
            json={"job_description": "Test JD for a Python developer"},
        )

    assert resp.status_code == 200
    events = _parse_sse(resp.text)

    event_types = [e["event"] for e in events]
    assert event_types[0] == "status"  # starting
    assert event_types[-1] == "status"  # done
    assert events[0]["data"] == "starting"
    assert events[-1]["data"] == "done"

    task_events = [e for e in events if e["event"] == "task"]
    assert len(task_events) == 4
    task_names = [json.loads(e["data"])["task"] for e in task_events]
    assert set(task_names) == {"skills", "cover", "emails", "ats"}


def test_generate_error(client):
    """Pipeline exception should produce an error SSE event."""

    def _failing_gen(*args, **kwargs):
        raise RuntimeError("Ollama exploded")

    with patch(
        "resumate.routes.generate.generate_application_package",
        side_effect=_failing_gen,
    ):
        resp = client.post(
            "/generate",
            json={"job_description": "Test JD"},
        )

    assert resp.status_code == 200  # SSE always returns 200
    events = _parse_sse(resp.text)
    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) == 1
    assert "Ollama exploded" in json.loads(error_events[0]["data"])["message"]
