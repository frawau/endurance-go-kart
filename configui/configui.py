#!/usr/bin/env python3
"""Go-Kart Config UI — a small HTTPS web service for configuring the system.

Standalone asyncio (aiohttp) service deployed natively via
``race-manager deploy-configui``. It edits the host ``.env``, manages named
Location profiles and runs allow-listed ``race-manager`` commands with live
output, so operators never have to touch the CLI.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from pathlib import Path
from urllib.parse import urlencode

import aiohttp_jinja2
import jinja2
from aiohttp import web

import auth
import commands
import proxytoml
import racelock
import schema
import tls
from envfile import EnvFile
from locations import LocationError, LocationStore

_log = logging.getLogger("configui")

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
ENV_PATH = Path(os.environ.get("CONFIGUI_ENV_PATH", REPO_ROOT / ".env"))
STATE_DIR = Path(os.environ.get("CONFIGUI_STATE_DIR", "/var/lib/configui"))
PROXY_TOML = Path(
    os.environ.get("CONFIGUI_PROXY_TOML", REPO_ROOT / "proxy" / "nettag-proxy.toml")
)
# The Django app (for the race-state lock check). Same host:port the timing
# station uses — gunicorn is published on 127.0.0.1:5005.
APP_URL = os.environ.get("CONFIGUI_APP_URL", "http://127.0.0.1:5005")
# Manual-SSL certificates live here (the fixed names `install-cert` expects).
SSL_DIR = Path(os.environ.get("CONFIGUI_SSL_DIR", REPO_ROOT / "ssl"))
TEMPLATES_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"


def _to_int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# Config access (os.environ overrides .env, which overrides defaults)
# --------------------------------------------------------------------------


def cfg(key: str, default: str | None = None) -> str | None:
    env_override = os.environ.get(key)
    if env_override is not None:
        return env_override
    value, _active = EnvFile(ENV_PATH).get(key)
    if value:
        return value
    return default


def hostname() -> str:
    return cfg("APP_HOSTNAME") or socket.gethostname() or "localhost"


def password() -> str:
    return cfg("CONFIGUI_PASSWORD") or ""


# --------------------------------------------------------------------------
# Auth middleware
# --------------------------------------------------------------------------

PUBLIC_PATHS = {"/login", "/favicon.ico"}

# Cookies are Secure by default (the service is HTTPS-only). The knob exists
# only for local plaintext testing.
COOKIE_SECURE = os.environ.get("CONFIGUI_COOKIE_SECURE", "1").lower() not in (
    "0",
    "false",
    "no",
)


@web.middleware
async def auth_middleware(request: web.Request, handler):
    path = request.path
    if path in PUBLIC_PATHS or path.startswith("/static/"):
        return await handler(request)

    token = request.cookies.get(auth.COOKIE_NAME, "")
    if not auth.verify_session(token, password(), int(time.time())):
        if path.startswith("/ws/"):
            return web.Response(status=401, text="unauthorized")
        raise web.HTTPFound("/login")
    return await handler(request)


def _require_csrf(request: web.Request, form) -> None:
    if not auth.check_csrf(form.get("csrf", ""), password()):
        raise web.HTTPForbidden(text="Invalid CSRF token")


async def current_lock() -> dict:
    return await racelock.lock_state(APP_URL)


async def _require_unlocked() -> None:
    """Block a mutating action while a round is live (hard lock)."""
    lock = await current_lock()
    if lock["locked"]:
        raise web.HTTPForbidden(
            text=f"Locked: {lock['reason'] or 'a round is in progress'} "
            "Configuration changes are disabled until the round ends."
        )


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------


@aiohttp_jinja2.template("login.html")
async def login_get(request: web.Request):
    return {"error": request.query.get("error")}


async def login_post(request: web.Request):
    form = await request.post()
    if not auth.check_password(form.get("password", ""), password()):
        raise web.HTTPFound("/login?error=1")
    token = auth.make_session(password(), int(time.time()))
    resp = web.HTTPFound("/")
    resp.set_cookie(
        auth.COOKIE_NAME,
        token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="Strict",
        max_age=auth.DEFAULT_MAX_AGE,
    )
    return resp


async def logout(request: web.Request):
    resp = web.HTTPFound("/login")
    resp.del_cookie(auth.COOKIE_NAME)
    return resp


@aiohttp_jinja2.template("dashboard.html")
async def dashboard(request: web.Request):
    store = LocationStore(ENV_PATH, STATE_DIR, PROXY_TOML)
    return {
        "page": "dashboard",
        "csrf": auth.csrf_token(password()),
        "commands": commands.COMMANDS,
        "sections": commands.SECTIONS,
        "active_location": store.active(),
        "hostname": hostname(),
        "auto_apply": request.query.get("apply"),
        "lock": await current_lock(),
        "read_only": sorted(commands.READ_ONLY),
    }


@aiohttp_jinja2.template("env.html")
async def env_get(request: web.Request):
    env = EnvFile(ENV_PATH)
    groups = []
    for group in schema.SCHEMA:
        fields = []
        for f in group.fields:
            value, active = env.get(f.key)
            fields.append({"f": f, "value": value or "", "active": active})
        groups.append({"title": group.title, "fields": fields})
    return {
        "page": "env",
        "csrf": auth.csrf_token(password()),
        "groups": groups,
        "saved": request.query.get("saved"),
        "ssl_uploaded": request.query.get("ssl_uploaded"),
        "ssl_error": request.query.get("ssl_error"),
        "lock": await current_lock(),
    }


def _read_upload(form, name: str) -> bytes | None:
    field = form.get(name)
    if field is None or isinstance(field, str):
        return None
    data = field.file.read()
    return data or None


async def ssl_upload(request: web.Request):
    """Save uploaded manual-SSL PEM files to ssl/fullchain.pem and privkey.pem."""
    form = await request.post()
    _require_csrf(request, form)
    await _require_unlocked()

    cert = _read_upload(form, "cert")
    key = _read_upload(form, "key")
    if not cert and not key:
        raise web.HTTPFound(
            "/env?" + urlencode({"ssl_error": "Choose a file to upload."})
        )
    for label, data in (("certificate", cert), ("private key", key)):
        if data is not None and not data.lstrip().startswith(b"-----BEGIN"):
            raise web.HTTPFound(
                "/env?" + urlencode({"ssl_error": f"The {label} is not a PEM file."})
            )

    SSL_DIR.mkdir(parents=True, exist_ok=True)
    if cert is not None:
        (SSL_DIR / "fullchain.pem").write_bytes(cert)
    if key is not None:
        key_path = SSL_DIR / "privkey.pem"
        key_path.write_bytes(key)
        key_path.chmod(0o600)
    raise web.HTTPFound("/env?ssl_uploaded=1")


async def env_post(request: web.Request):
    form = await request.post()
    _require_csrf(request, form)
    await _require_unlocked()
    env = EnvFile(ENV_PATH)
    for f in schema.all_fields():
        if f.key not in form:
            continue
        submitted = form[f.key].strip()
        current, active = env.get(f.key)
        # Leave commented defaults untouched when the user submits nothing.
        if submitted == "" and not active:
            continue
        if submitted != (current or ""):
            env.set(f.key, submitted)
    env.save()
    raise web.HTTPFound("/env?saved=1")


@aiohttp_jinja2.template("locations.html")
async def locations_get(request: web.Request):
    store = LocationStore(ENV_PATH, STATE_DIR, PROXY_TOML)
    return {
        "page": "locations",
        "csrf": auth.csrf_token(password()),
        "locations": store.list(),
        "active": store.active(),
        "msg": request.query.get("msg"),
        "error": request.query.get("error"),
        "lock": await current_lock(),
    }


async def locations_post(request: web.Request):
    form = await request.post()
    _require_csrf(request, form)
    store = LocationStore(ENV_PATH, STATE_DIR, PROXY_TOML)
    action = form.get("action", "")
    name = form.get("name", "")
    try:
        if action == "save":
            store.save(name)
            msg = f"Saved current configuration as '{name}'."
        elif action == "switch":
            # Switching restarts services, so it's blocked during a live round.
            await _require_unlocked()
            store.switch(name)
            # Switch is applied to running services on the dashboard (auto-run).
            raise web.HTTPFound("/?apply=1")
        elif action == "delete":
            store.delete(name)
            msg = f"Deleted '{name}'."
        else:
            raise LocationError("Unknown action.")
    except LocationError as exc:
        raise web.HTTPFound("/locations?" + urlencode({"error": str(exc)}))
    raise web.HTTPFound("/locations?" + urlencode({"msg": msg}))


@aiohttp_jinja2.template("proxy.html")
async def proxy_get(request: web.Request):
    data = proxytoml.load(PROXY_TOML)
    # Seed the decoder address from the timing station's direct-mode address
    # when the proxy upstream hasn't been set yet.
    if not data["upstream"]["decoder_host"]:
        direct_host = cfg("TIMING_NETTAG_HOST")
        if direct_host and direct_host not in proxytoml.LOCAL_HOSTS:
            data["upstream"]["decoder_host"] = direct_host
            data["upstream"]["decoder_port"] = (
                cfg("TIMING_NETTAG_PORT") or data["upstream"]["decoder_port"]
            )
    local_port, extras = proxytoml.split_clients(data)
    deployed = Path("/etc/systemd/system/nettag-proxy.service").exists()
    return {
        "page": "proxy",
        "csrf": auth.csrf_token(password()),
        "data": data,
        "local_port": local_port,
        "extras": extras,
        "log_levels": ["DEBUG", "INFO", "WARNING", "ERROR"],
        "deployed": deployed,
        "saved": request.query.get("saved"),
        "error": request.query.get("error"),
        "lock": await current_lock(),
    }


async def proxy_post(request: web.Request):
    form = await request.post()
    _require_csrf(request, form)
    await _require_unlocked()

    listen_port = _to_int(form.get("listen_port"), 2010)
    local_port = _to_int(form.get("local_port"), 2011)
    # The proxy binds listen_port; the loopback timing station holds local_port.
    # If they're equal the proxy can't bind, so refuse to save.
    if listen_port == local_port:
        raise web.HTTPFound(
            "/proxy?"
            + urlencode(
                {
                    "error": f"ACK listen port and the local timing client port must "
                    f"differ (both are {listen_port})."
                }
            )
        )

    data = proxytoml.load(PROXY_TOML)
    data["upstream"]["decoder_host"] = form.get("decoder_host", "").strip()
    data["upstream"]["decoder_port"] = _to_int(form.get("decoder_port"), 2009)
    data["downstream"]["listen_port"] = listen_port
    data["downstream"]["resend_interval"] = _to_float(form.get("resend_interval"), 1.0)
    data["logging"]["level"] = form.get("log_level", "INFO")

    # Local timing client first, then any extra clients (blank hosts dropped).
    clients = [{"host": "127.0.0.1", "port": local_port}]
    hosts = form.getall("client_host", [])
    ports = form.getall("client_port", [])
    for host, port in zip(hosts, ports):
        host = host.strip()
        if host:
            clients.append({"host": host, "port": _to_int(port, 0)})
    data["clients"] = clients

    proxytoml.dump(PROXY_TOML, data)
    raise web.HTTPFound("/proxy?saved=1")


async def ws_run(request: web.Request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    async for raw in ws:
        if raw.type != web.WSMsgType.TEXT:
            continue
        try:
            data = raw.json()
        except Exception:
            await ws.send_str("refused: bad message\n")
            continue
        if not auth.check_csrf(data.get("csrf", ""), password()):
            await ws.send_str("refused: invalid CSRF token\n__EXIT__ 1\n")
            continue
        name = data.get("cmd", "")
        if not commands.is_allowed(name):
            await ws.send_str(f"refused: unknown command {name!r}\n__EXIT__ 1\n")
            continue
        if not commands.is_read_only(name):
            lock = await current_lock()
            if lock["locked"]:
                await ws.send_str(
                    f"refused: {lock['reason'] or 'a round is in progress'} "
                    "Commands that change the system are disabled until the round ends.\n"
                    "__EXIT__ 1\n"
                )
                continue
        async for line in commands.run(REPO_ROOT, name):
            await ws.send_str(line)
    return ws


# --------------------------------------------------------------------------
# App factory + entrypoint
# --------------------------------------------------------------------------


def make_app() -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)))
    app.add_routes(
        [
            web.get("/login", login_get),
            web.post("/login", login_post),
            web.get("/logout", logout),
            web.post("/logout", logout),
            web.get("/", dashboard),
            web.get("/env", env_get),
            web.post("/env", env_post),
            web.post("/ssl/upload", ssl_upload),
            web.get("/locations", locations_get),
            web.post("/locations", locations_post),
            web.get("/proxy", proxy_get),
            web.post("/proxy", proxy_post),
            web.get("/ws/run", ws_run),
            web.static("/static", STATIC_DIR),
        ]
    )
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    bind = cfg("CONFIGUI_BIND", "0.0.0.0")
    port = int(cfg("CONFIGUI_PORT", "7443"))
    ssl_ctx, self_signed = tls.make_ssl_context(REPO_ROOT, STATE_DIR, hostname())

    if not password():
        _log.warning(
            "CONFIGUI_PASSWORD is not set — login will reject everyone. Run deploy-configui."
        )
    _log.info(
        "Config UI on https://%s:%s/ (%s cert)",
        hostname(),
        port,
        "self-signed" if self_signed else "real",
    )
    web.run_app(make_app(), host=bind, port=port, ssl_context=ssl_ctx, print=None)


if __name__ == "__main__":
    main()
