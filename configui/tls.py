"""TLS material resolution for the config UI.

Selection order (self-healing on startup):

1. A real certificate in the repo ``ssl/`` directory (the same paths the main
   app uses) — ``fullchain.pem`` + ``privkey.pem``.
2. A previously generated self-signed pair in the state dir.
3. Otherwise generate a fresh self-signed pair in the state dir and use it.
"""

from __future__ import annotations

import ssl
import subprocess
from pathlib import Path

_log_prefix = "[tls]"


def _pair_exists(cert: Path, key: Path) -> bool:
    return cert.is_file() and key.is_file()


def resolve_cert(
    repo_root: Path, state_dir: Path, hostname: str
) -> tuple[Path, Path, bool]:
    """Return ``(cert_path, key_path, is_self_signed)``.

    Generates a self-signed pair when no usable certificate is found.
    """
    real_cert = repo_root / "ssl" / "fullchain.pem"
    real_key = repo_root / "ssl" / "privkey.pem"
    if _pair_exists(real_cert, real_key):
        return real_cert, real_key, False

    ss_dir = state_dir / "ssl"
    ss_cert = ss_dir / "cert.pem"
    ss_key = ss_dir / "key.pem"
    if _pair_exists(ss_cert, ss_key):
        return ss_cert, ss_key, True

    generate_self_signed(ss_cert, ss_key, hostname)
    return ss_cert, ss_key, True


def generate_self_signed(cert: Path, key: Path, hostname: str) -> None:
    cert.parent.mkdir(parents=True, exist_ok=True)
    cn = hostname or "localhost"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-nodes",
            "-newkey",
            "rsa:2048",
            "-days",
            "3650",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            f"/CN={cn}",
            "-addext",
            f"subjectAltName=DNS:{cn},DNS:localhost,IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    key.chmod(0o600)


def make_ssl_context(
    repo_root: Path, state_dir: Path, hostname: str
) -> tuple[ssl.SSLContext, bool]:
    cert, key, self_signed = resolve_cert(repo_root, state_dir, hostname)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert), keyfile=str(key))
    return ctx, self_signed
