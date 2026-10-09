"""Model management + performance stats API routes."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from resumate.config.settings import MODEL_CONFIG_FILE, OLLAMA_HOST, ROOT
from resumate.middleware.auth import get_current_user
from resumate.models.llm import get_current_model, reload_model

logger = logging.getLogger("resumate")
router = APIRouter(tags=["models"])

PERF_LOG = ROOT / "logs" / "performance.json"


# ── Schemas ──────────────────────────────────────────────────────────

class ModelSelectRequest(BaseModel):
    model_name: str
    temperature: float | None = None
    max_tokens: dict[str, int] | None = None
    context_limits: dict[str, int] | None = None


# ── GET /api/models — list installed Ollama models ───────────────────

@router.get("/api/models")
async def list_models(request: Request):
    user = get_current_user(request)
    current = get_current_model()

    # Fetch installed models from Ollama
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            tags_resp = await client.get(f"{OLLAMA_HOST}/api/tags")
            tags_resp.raise_for_status()
            tags_data = tags_resp.json()

            # Also get running models for VRAM info
            ps_resp = await client.get(f"{OLLAMA_HOST}/api/ps")
            ps_data = ps_resp.json() if ps_resp.status_code == 200 else {}
    except Exception as exc:
        raise HTTPException(502, f"Cannot reach Ollama: {exc}") from exc

    running_models = {
        m.get("name", ""): m for m in ps_data.get("models", [])
    }

    models = []
    for m in tags_data.get("models", []):
        name = m.get("name", "")
        size_bytes = m.get("size", 0)
        details = m.get("details", {})
        running = running_models.get(name, {})

        models.append({
            "name": name,
            "size_gb": round(size_bytes / 1e9, 2),
            "parameter_size": details.get("parameter_size", ""),
            "quantization": details.get("quantization_level", ""),
            "family": details.get("family", ""),
            "is_current": name == current,
            "is_loaded": name in running_models,
            "vram_gb": round(running.get("size_vram", 0) / 1e9, 2) if running else 0,
            "compute": "gpu" if running.get("size_vram", 0) > 0 else ("cpu" if running else "not_loaded"),
        })

    # Sort: current first, then loaded, then by size
    models.sort(key=lambda x: (not x["is_current"], not x["is_loaded"], x["size_gb"]))

    return {"current": current, "models": models}


# ── POST /api/models/select — switch active model ───────────────────

@router.post("/api/models/select")
async def select_model(request: Request, body: ModelSelectRequest):
    user = get_current_user(request)

    # Verify model exists in Ollama
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_HOST}/api/tags")
            resp.raise_for_status()
            installed = [m["name"] for m in resp.json().get("models", [])]
    except Exception as exc:
        raise HTTPException(502, f"Cannot reach Ollama: {exc}") from exc

    if body.model_name not in installed:
        raise HTTPException(404, f"Model '{body.model_name}' not installed in Ollama")

    # Update model_config.yaml
    try:
        config = yaml.safe_load(MODEL_CONFIG_FILE.read_text()) or {}
        config.setdefault("llm", {})["model_name"] = body.model_name
        if body.temperature is not None:
            config["llm"]["temperature"] = body.temperature
        if body.max_tokens:
            config["llm"]["max_tokens"] = body.max_tokens
        if body.context_limits:
            config.setdefault("runtime", {})["context_limits"] = body.context_limits

        MODEL_CONFIG_FILE.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    except Exception as exc:
        logger.error("Failed to update model_config.yaml: %s", exc)
        raise HTTPException(500, "Failed to save config") from exc

    # Hot-reload the LLM singleton
    reload_model(body.model_name, body.temperature)

    # Trigger warm-up in background (fire and forget)
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(
                f"{OLLAMA_HOST}/api/generate",
                json={"model": body.model_name, "prompt": "hi", "stream": False},
            )
    except Exception:
        pass  # warm-up is best-effort

    logger.info("Model switched to %s", body.model_name)
    return {"status": "ok", "model": body.model_name}


# ── POST /api/models/reload — dev-TUI hook (localhost only, no auth) ──

@router.post("/api/models/reload")
async def reload_active_model(request: Request, body: ModelSelectRequest):
    """Hot-reload the LLM singleton and warm it up. The caller (dev TUI) has
    already written model_config.yaml. Restricted to loopback clients."""
    if not request.client or request.client.host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(403, "localhost only")

    reload_model(body.model_name, body.temperature)
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            await client.post(
                f"{OLLAMA_HOST}/api/generate",
                json={"model": body.model_name, "prompt": "hi", "stream": False, "keep_alive": "24h"},
            )
    except Exception:
        pass  # warm-up is best-effort

    logger.info("Model reloaded (dev TUI) → %s", body.model_name)
    return {"status": "ok", "model": body.model_name}


# ── GET /api/stats — performance summary ────────────────────────────

@router.get("/api/stats")
async def get_stats(request: Request):
    user = get_current_user(request)

    if not PERF_LOG.exists():
        return {"runs": [], "summary": {}}

    # Parse last N lines of JSONL
    lines = PERF_LOG.read_text().strip().splitlines()

    # Only keep generation entries (not ttft sub-entries)
    entries = []
    for line in reversed(lines):
        try:
            d = json.loads(line)
            if d.get("stage") == "generation" and d.get("status") == "ok":
                entries.append(d)
        except (json.JSONDecodeError, KeyError):
            continue
        if len(entries) >= 20:
            break

    entries.reverse()

    # Group by run (consecutive 4-task blocks)
    task_names = {"gen_skills", "gen_cover", "gen_emails", "gen_ats"}
    runs: list[dict] = []
    current_run: list[dict] = []

    for e in entries:
        tn = e.get("task_name", "")
        if tn in task_names:
            current_run.append(e)
            if len(current_run) == 4:
                total_ms = sum(t.get("total_ms", 0) for t in current_run)
                avg_ttft = sum(t.get("ttft_ms", 0) or 0 for t in current_run) / 4
                runs.append({
                    "tasks": [
                        {
                            "name": t["task_name"].replace("gen_", ""),
                            "ttft_ms": round(t.get("ttft_ms", 0) or 0),
                            "total_ms": round(t.get("total_ms", 0)),
                        }
                        for t in current_run
                    ],
                    "total_ms": round(total_ms),
                    "avg_ttft_ms": round(avg_ttft),
                })
                current_run = []

    # Summary across all runs
    summary = {}
    if runs:
        all_totals = [r["total_ms"] for r in runs]
        all_ttfts = [r["avg_ttft_ms"] for r in runs]
        summary = {
            "run_count": len(runs),
            "avg_total_ms": round(sum(all_totals) / len(all_totals)),
            "best_total_ms": round(min(all_totals)),
            "worst_total_ms": round(max(all_totals)),
            "avg_ttft_ms": round(sum(all_ttfts) / len(all_ttfts)),
        }

    # Return last 5 runs
    return {"runs": runs[-5:], "summary": summary}


# ── GET /api/models/config — current model config ───────────────────

@router.get("/api/models/config")
async def get_model_config(request: Request):
    user = get_current_user(request)
    config = yaml.safe_load(MODEL_CONFIG_FILE.read_text()) or {}
    llm = config.get("llm", {})
    runtime = config.get("runtime", {})
    return {
        "model_name": llm.get("model_name", ""),
        "temperature": llm.get("temperature", 0.2),
        "max_tokens": llm.get("max_tokens", {}),
        "context_limits": runtime.get("context_limits", {}),
    }
