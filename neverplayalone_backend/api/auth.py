from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from .config import load_config

try:
    import bittensor as bt
except ImportError:  # pragma: no cover
    bt = None


@dataclass(frozen=True)
class AuthContext:
    hotkey: str


async def verify_signed_hotkey(request: Request) -> AuthContext:
    config = load_config()
    if config.auth_disabled:
        return AuthContext(hotkey="auth-disabled")

    hotkey = request.headers.get("X-Hotkey")
    nonce = request.headers.get("X-Nonce")
    signature = request.headers.get("X-Signature")
    timestamp = request.headers.get("X-Timestamp")
    if not (hotkey and nonce and signature and timestamp):
        raise HTTPException(401, "missing auth headers")

    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise HTTPException(401, "bad timestamp") from exc
    if abs(int(time.time()) - ts) > config.signature_max_age:
        raise HTTPException(401, "stale request")
    if bt is None:
        raise HTTPException(500, "bittensor is required when auth is enabled")

    body = await request.body()
    message = f"{request.method}\n{request.url.path}\n{body.decode('utf-8')}\n{nonce}\n{timestamp}"
    try:
        keypair = bt.Keypair(ss58_address=hotkey)
        ok = keypair.verify(message.encode("utf-8"), bytes.fromhex(signature))
    except Exception as exc:  # pragma: no cover
        raise HTTPException(401, "signature verification error") from exc
    if not ok:
        raise HTTPException(401, "invalid signature")
    return AuthContext(hotkey=hotkey)


async def verify_owner(request: Request) -> AuthContext:
    auth = await verify_signed_hotkey(request)
    config = load_config()
    if config.auth_disabled:
        return auth
    if not config.owner_hotkey:
        raise HTTPException(500, "owner hotkey is not configured")
    if auth.hotkey != config.owner_hotkey:
        raise HTTPException(403, "owner-only endpoint")
    return auth


async def verify_validator(request: Request) -> AuthContext:
    return await verify_signed_hotkey(request)


async def verify_miner(request: Request) -> AuthContext:
    return await verify_signed_hotkey(request)
