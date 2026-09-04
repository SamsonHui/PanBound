"""通用 OIDC 客户端 (Authorization Code Flow)。

企业微信/飞书/钉钉 都是 OAuth2/OIDC 兼容,只换 field mapping 与端点 URL 即可。
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests

from ..extensions import get_redis

logger = logging.getLogger(__name__)

_STATE_PREFIX = "oidc:state:"
_STATE_TTL = 600  # 10min


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_state(provider_id: int, next_url: str = "/") -> str:
    """生成 state 并写入 Redis。

    Redis 里存 {"provider_id": int, "next": str},TTL 10 分钟。
    """
    state = _b64url_encode(secrets.token_bytes(24))
    payload = json.dumps({"provider_id": int(provider_id), "next": next_url})
    try:
        get_redis().setex(f"{_STATE_PREFIX}{state}", _STATE_TTL, payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("写 OIDC state 失败:%s", exc)
    return state


def consume_state(state: str) -> dict[str, Any] | None:
    """校验并消费 state。成功返回 payload,失败/过期返回 None。"""
    if not state:
        return None
    try:
        r = get_redis()
        raw = r.get(f"{_STATE_PREFIX}{state}")
        r.delete(f"{_STATE_PREFIX}{state}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("读 OIDC state 失败:%s", exc)
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


@dataclass
class OIDCEndpoints:
    authorize_url: str
    token_url: str
    userinfo_url: str


def build_authorize_url(
    *,
    authorize_url: str,
    client_id: str,
    redirect_uri: str,
    scope: str,
    state: str,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
    }
    return f"{authorize_url}?{urlencode(params)}"


def exchange_code(
    *,
    token_url: str,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    extra: dict[str, str] | None = None,
    timeout: int = 15,
) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    if extra:
        data.update(extra)
    try:
        r = requests.post(token_url, data=data, timeout=timeout)
    except requests.RequestException as exc:
        raise OIDCError(f"OIDC token 网络失败:{exc}") from exc
    if r.status_code >= 400:
        raise OIDCError(f"OIDC token HTTP {r.status_code}: {r.text[:400]}")
    try:
        return r.json()
    except ValueError as exc:
        raise OIDCError(f"OIDC token 响应非 JSON: {r.text[:200]}") from exc


def fetch_userinfo(
    *,
    userinfo_url: str,
    access_token: str,
    timeout: int = 15,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        r = requests.get(userinfo_url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise OIDCError(f"OIDC userinfo 网络失败:{exc}") from exc
    if r.status_code >= 400:
        raise OIDCError(f"OIDC userinfo HTTP {r.status_code}: {r.text[:400]}")
    try:
        return r.json()
    except ValueError as exc:
        raise OIDCError(f"OIDC userinfo 响应非 JSON: {r.text[:200]}") from exc


def extract_user_fields(userinfo: dict[str, Any], provider) -> dict[str, str | None]:
    """根据 provider 配置的字段映射,从 userinfo 中拿值。"""
    def _get(field: str) -> str | None:
        if not field:
            return None
        v = userinfo.get(field)
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    return {
        "subject": _get(provider.subject_field),
        "username": _get(provider.username_field),
        "email": _get(provider.email_field),
        "display_name": _get(provider.display_name_field),
    }


class OIDCError(RuntimeError):
    pass
