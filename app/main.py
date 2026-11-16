"""Application Dépenses : réception SMS + consultation web."""
from __future__ import annotations

import csv
import hmac
import time
from collections import defaultdict
import io
import logging
from datetime import date, datetime

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from starlette.middleware.sessions import SessionMiddleware

from . import config, service
from .db import engine, expenses, init_db
from .parser import ALL_CATEGORIES, guess_category, normalize_phone
from .sms import send_sms

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(_app):
    config.check_production_config()
    init_db()
    yield


app = FastAPI(title="Dépenses", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    h = response.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "same-origin"
    h["Content-Security-Policy"] = ("default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                    "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
    if config.PRODUCTION:
        h["Strict-Transport-Security"] = "max-age=31536000"
    return response


def same_text(a: str, b: str) -> bool:
    return hmac.compare_digest((a or "").encode(), (b or "").encode())


# Anti force brute : 5 essais ratés par IP sur 15 minutes
_FAILS: dict[str, list[float]] = defaultdict(list)
MAX_FAILS, WINDOW = 5, 15 * 60


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def too_many_fails(ip: str) -> bool:
    now = time.time()
    _FAILS[ip] = [t for t in _FAILS[ip] if now - t < WINDOW]
    return len(_FAILS[ip]) >= MAX_FAILS
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, max_age=60 * 60 * 24 * 30,
                   https_only=config.PRODUCTION, same_site="strict")
templates = Jinja2Templates(directory=str(__import__("pathlib").Path(__file__).parent / "templates"))
templates.env.filters["money"] = service.fmt


@app.get("/health")
def health():
    return {"ok": True}


# ---------------------------------------------------------------- SMS
def _extract_sms(body: dict) -> tuple[str, str, str | None]:
    """Accepte le format SMS Gateway for Android et un format générique {from, text}."""
    if "payload" in body:
        p = body.get("payload") or {}
        sender = p.get("sender") or p.get("phoneNumber") or ""
        return sender, p.get("message") or "", p.get("messageId") or body.get("id")
    return (body.get("from") or body.get("sender") or "",
            body.get("text") or body.get("message") or "", body.get("id"))


@app.post("/webhook/sms")
async def sms_webhook(request: Request, background: BackgroundTasks, token: str = ""):
    if not same_text(token, config.WEBHOOK_TOKEN):
        raise HTTPException(403, "token invalide")
    raw = await request.body()
    if len(raw) > 20_000:
        raise HTTPException(413, "trop gros")
    try:
        body = __import__("json").loads(raw)
        assert isinstance(body, dict)
    except Exception:
        raise HTTPException(400, "JSON invalide")
    if body.get("event") and body["event"] != "sms:received":
        return {"ignored": body["event"]}
    sender, text, msg_id = _extract_sms(body)
    user = config.user_by_phone(sender)
    if not user:
        log.warning("SMS ignoré d'un numéro inconnu : %s", sender)
        return {"ignored": "numero inconnu"}
    if service.already_processed(msg_id):
        return {"ignored": "doublon"}
    reply = service.handle_sms(user.name, text)
    log.info("SMS %s (%s) : %r -> %r", user.name, sender, text, reply)
    background.add_task(send_sms, user.phone, reply)
    return {"user": user.name, "reply": reply}


# ---------------------------------------------------------------- Web : auth
def current_user(request: Request):
    return config.user_by_name(request.session.get("user", ""))


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse(request, "login.html",
                                      {"users": config.USERS, "error": error})


@app.post("/login")
def login(request: Request, name: str = Form(...), password: str = Form(...)):
    ip = client_ip(request)
    if too_many_fails(ip):
        return RedirectResponse("/login?error=2", status_code=303)
    u = config.user_by_name(name)
    if not u or not same_text(password, u.password):
        _FAILS[ip].append(time.time())
        time.sleep(0.5)
        return RedirectResponse("/login?error=1", status_code=303)
    _FAILS.pop(ip, None)
    request.session.clear()
    request.session["user"] = u.name
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------------------------------------------------------------- Web : tableau de bord
def _parse_month(month: str | None) -> date:
    try:
        return datetime.strptime(month, "%Y-%m").date()
    except (TypeError, ValueError):
        return date.today().replace(day=1)


def _shift(d: date, n: int) -> str:
    m = d.month - 1 + n
    return f"{d.year + m // 12:04d}-{m % 12 + 1:02d}"


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, month: str | None = None, who: str = "foyer"):
    me = current_user(request)
    if not me:
        return RedirectResponse("/login", status_code=303)
    m = _parse_month(month)
    start, end = service.month_bounds(m)
    names = [u.name for u in config.USERS]
    who = who if who in names else "foyer"

    base = [expenses.c.spent_on >= start, expenses.c.spent_on < end]
    scoped = base + ([expenses.c.user == who] if who != "foyer" else [])
    with engine.connect() as c:
        rows = c.execute(select(expenses).where(*scoped)
                         .order_by(expenses.c.spent_on.desc(), expenses.c.id.desc())).fetchall()
        by_cat = c.execute(select(expenses.c.category, func.sum(expenses.c.amount).label("t"))
                           .where(*scoped).group_by(expenses.c.category)
                           .order_by(func.sum(expenses.c.amount).desc())).fetchall()
        by_user = dict(c.execute(select(expenses.c.user, func.sum(expenses.c.amount))
                                 .where(*base).group_by(expenses.c.user)).fetchall())
    total = sum(r.amount for r in rows)
    prev_total = service.month_total(None if who == "foyer" else who,
                                     date.fromisoformat(_shift(m, -1) + "-01"))
    return templates.TemplateResponse(request, "dashboard.html", {
        "me": me, "users": config.USERS, "who": who, "month": m, "rows": rows,
        "total": total, "prev_total": prev_total, "by_cat": by_cat,
        "by_user": {n: by_user.get(n, 0) for n in names}, "household": sum(by_user.values()),
        "prev": _shift(m, -1), "next": _shift(m, 1), "month_str": f"{m:%Y-%m}",
        "categories": ALL_CATEGORIES, "today": date.today().isoformat(),
        "max_cat": max([t for _, t in by_cat] or [1]),
    })


@app.post("/expenses")
def add_expense_web(request: Request, amount: str = Form(...), description: str = Form(""),
                    category: str = Form(""), spent_on: str = Form(""), user: str = Form("")):
    me = current_user(request)
    if not me:
        return RedirectResponse("/login", status_code=303)
    try:
        value = float(amount.replace(",", "."))
        assert value > 0
    except Exception:
        raise HTTPException(400, "montant invalide")
    target = config.user_by_name(user) or me
    cat = category if category in ALL_CATEGORIES else guess_category(description)
    d = date.fromisoformat(spent_on) if spent_on else date.today()
    service.add_expense(target.name, value, description.strip() or "Sans description", cat, d, "web")
    return RedirectResponse(f"/?month={d:%Y-%m}&who={request.query_params.get('who', 'foyer')}",
                            status_code=303)


@app.post("/expenses/{expense_id}/delete")
def delete_expense(request: Request, expense_id: int):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    with engine.begin() as c:
        c.execute(delete(expenses).where(expenses.c.id == expense_id))
    ref = request.headers.get("referer", "/")
    from urllib.parse import urlparse
    u = urlparse(ref)
    target = (u.path or "/") + (("?" + u.query) if u.query else "")
    return RedirectResponse(target if target.startswith("/") else "/", status_code=303)


@app.get("/export.csv")
def export_csv(request: Request):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    with engine.connect() as c:
        rows = c.execute(select(expenses).order_by(expenses.c.spent_on)).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["date", "personne", "montant", "description", "categorie", "canal"])
    for r in rows:
        w.writerow([r.spent_on, r.user, f"{r.amount:.2f}".replace(".", ","), r.description,
                    r.category, r.channel])
    return StreamingResponse(iter(["﻿" + buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=depenses.csv"})


# ---------------------------------------------------------------- Simulateur SMS (tests)
@app.get("/simulateur", response_class=HTMLResponse)
def simulator(request: Request):
    me = current_user(request)
    if not me:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "simulator.html", {"me": me, "users": config.USERS})


@app.post("/simulateur")
async def simulator_send(request: Request):
    if not current_user(request):
        raise HTTPException(401)
    data = await request.json()
    u = config.user_by_name(data.get("user", ""))
    if not u:
        raise HTTPException(400, "utilisateur inconnu")
    return JSONResponse({"reply": service.handle_sms(u.name, data.get("text", ""))})
