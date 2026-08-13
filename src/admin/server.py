from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.activity.store import ActivityStore
from src.admin.auth import AdminAuth
from src.config import get_settings
from src.models import format_datetime
from src.web.security import MAX_PASSWORD_LEN, client_ip

log = logging.getLogger("gift-admin")
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.autoescape = True

SESSION_COOKIE = "lg_sid"

NOT_FOUND_HTML = """<!DOCTYPE html>
<html>
<head><title>404 Not Found</title></head>
<body bgcolor="white">
<center><h1>404 Not Found</h1></center>
<hr><center>nginx</center>
</body>
</html>"""

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
_auth: AdminAuth | None = None
_store: ActivityStore | None = None


def _not_found() -> HTMLResponse:
    return HTMLResponse(NOT_FOUND_HTML, status_code=404)


def _get_auth() -> AdminAuth:
    global _auth
    if _auth is None:
        settings = get_settings()
        _auth = AdminAuth(
            settings.redis_url,
            settings.admin_password_hash,
            settings.admin_session_secret,
        )
    return _auth


def _get_store() -> ActivityStore:
    global _store
    if _store is None:
        _store = ActivityStore(get_settings().redis_url)
        _store.connect()
    return _store


def _session_token(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def _authed(request: Request) -> bool:
    settings = get_settings()
    if not settings.admin_password_hash:
        return False
    return _get_auth().validate_session(_session_token(request), client_ip(request))


def _gate_path(request: Request) -> bool:
    settings = get_settings()
    gate = settings.admin_gate_path.strip("/")
    if not gate:
        return False
    path = request.url.path.strip("/")
    return path == gate


@app.middleware("http")
async def hide_fingerprint_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["Server"] = "nginx"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    if response.status_code == 404:
        response.headers["Content-Type"] = "text/html"
    return response


@app.get("/{full_path:path}", response_class=HTMLResponse)
async def stealth_get(request: Request, full_path: str = "") -> Response:
    if _authed(request):
        if request.url.path == "/logout":
            token = _session_token(request)
            _get_auth().revoke_session(token)
            resp = RedirectResponse("/", status_code=302)
            resp.delete_cookie(SESSION_COOKIE, httponly=True, secure=True, samesite="strict")
            return resp
        if _gate_path(request):
            return RedirectResponse("/", status_code=302)
        return _dashboard(request)

    if _gate_path(request):
        ip = client_ip(request)
        csrf = _get_auth().issue_csrf(ip)
        return TEMPLATES.TemplateResponse(request, "gate.html", {"csrf": csrf})

    return _not_found()


@app.post("/{full_path:path}")
async def stealth_post(
    request: Request,
    full_path: str = "",
    password: str = Form(default=""),
    csrf: str = Form(default=""),
) -> Response:
    if not _gate_path(request):
        return _not_found()

    if _authed(request):
        return RedirectResponse("/", status_code=302)

    settings = get_settings()
    if not settings.admin_password_hash:
        return _not_found()

    ip = client_ip(request)
    auth = _get_auth()
    if not auth.login_allowed(ip):
        return _not_found()
    if not auth.consume_csrf(csrf, ip):
        return _not_found()
    if len(password) > MAX_PASSWORD_LEN:
        return _not_found()

    token = auth.verify_login(password, ip)
    if not token:
        return _not_found()

    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=86400,
        path="/",
    )
    return response


def _dashboard(request: Request) -> HTMLResponse:
    store = _get_store()
    events = store.list_events(limit=300)
    chains = store.events_by_ip()
    stats = {
        "unique_ips": store.unique_ips(),
        "total_events": store.total_events(),
    }
    return TEMPLATES.TemplateResponse(
        request,
        "dashboard.html",
        {
            "events": events,
            "chains": chains,
            "stats": stats,
            "format_datetime": format_datetime,
        },
    )
