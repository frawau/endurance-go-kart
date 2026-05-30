"""Password check and stdlib-only signed session cookies.

No external crypto dependency: cookies are HMAC-signed with a key derived from
``CONFIGUI_PASSWORD``. A side effect is that changing the password invalidates
every existing session, which is exactly what we want.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

COOKIE_NAME = "configui_session"
DEFAULT_MAX_AGE = 12 * 3600  # 12 hours


def _key(password: str) -> bytes:
    return hashlib.sha256(b"configui-session-key:" + password.encode()).digest()


def check_password(submitted: str, configured: str) -> bool:
    """Constant-time password comparison. Empty configured password denies all."""
    if not configured:
        return False
    return hmac.compare_digest(submitted.encode(), configured.encode())


def _sign(key: bytes, payload: str) -> str:
    sig = hmac.new(key, payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def make_session(password: str, issued_at: int) -> str:
    """Create a signed session token stamped with *issued_at* (unix seconds)."""
    payload = str(issued_at)
    return f"{payload}.{_sign(_key(password), payload)}"


def verify_session(
    token: str, password: str, now: int, max_age: int = DEFAULT_MAX_AGE
) -> bool:
    if not token or not password:
        return False
    try:
        payload, sig = token.rsplit(".", 1)
        issued_at = int(payload)
    except (ValueError, AttributeError):
        return False
    expected = _sign(_key(password), payload)
    if not hmac.compare_digest(sig, expected):
        return False
    return 0 <= (now - issued_at) <= max_age


def csrf_token(password: str) -> str:
    """A stable per-password CSRF token (defence in depth atop SameSite=Strict)."""
    return _sign(_key(password), "csrf")


def check_csrf(submitted: str, password: str) -> bool:
    return bool(submitted) and hmac.compare_digest(submitted, csrf_token(password))
