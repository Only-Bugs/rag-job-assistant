"""Tests for GET /health endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx


def test_health_ollama_reachable(client):
    """When Ollama is reachable, status should be 'ok'."""
    mock_response = httpx.Response(200, json={"models": []})

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        resp = client.get("/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert "model" in data
    assert "model_ready" in data


def test_health_ollama_down(client):
    """When Ollama is unreachable, status should be 'degraded'."""
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("connection refused"),
    ):
        resp = client.get("/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["ollama_reachable"] is False
