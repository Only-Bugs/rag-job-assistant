"""Serve all HTML pages with proper routing and catch-all 404."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

from resumate.middleware.auth import check_session

router = APIRouter()

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
_PAGES_DIR = _FRONTEND_DIR / "pages"


def _page(name: str) -> FileResponse:
    return FileResponse(str(_PAGES_DIR / name))


@router.get("/")
async def serve_home(request: Request):
    if not check_session(request):
        return _page("landing.html")
    return _page("index.html")


@router.get("/about")
async def serve_about():
    return _page("about.html")


@router.get("/login")
async def serve_login(request: Request):
    if check_session(request):
        return RedirectResponse("/", status_code=302)
    return _page("login.html")


@router.get("/onboarding")
async def serve_onboarding(request: Request):
    if not check_session(request):
        return RedirectResponse("/login", status_code=302)
    return _page("onboarding.html")


@router.get("/workspace")
async def serve_workspace(request: Request):
    if not check_session(request):
        return RedirectResponse("/login", status_code=302)
    return _page("workspace.html")


@router.get("/settings")
async def serve_settings(request: Request):
    if not check_session(request):
        return RedirectResponse("/login", status_code=302)
    return _page("settings.html")


@router.get("/account")
async def serve_account(request: Request):
    if not check_session(request):
        return RedirectResponse("/login", status_code=302)
    return _page("account.html")
