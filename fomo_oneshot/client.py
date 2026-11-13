"""One HTTP GET per call. No cursor, no retry, no redirect."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import quote

from .constants import API_ORIGIN, FOLLOWING_PATH, HTTP_TIMEOUT_SECONDS, MAX_BODY_BYTES, MAX_REQUESTS, POSITIONS_PATH
from .guard import guarded_opener, raise_clean, safe_text
from .redact import redact
from .swap import normalize_handle

_CODE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


class CapError(Exception):
    def __init__(self) -> None:
        super().__init__("request cap reached; stopped")


class ProviderError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(redact(message))


class ProviderStop(ProviderError):
    def __init__(self, status: int, code: str | None) -> None:
        self.status = status
        self.code = code
        super().__init__(_stop_message(status, code))


@dataclass
class Budget:
    requested: int
    used: int = 0

    def __post_init__(self) -> None:
        if self.requested < 0:
            self.requested = 0
        if self.requested > MAX_REQUESTS:
            self.requested = MAX_REQUESTS

    @property
    def limit(self) -> int:
        return self.requested

    def allow(self) -> bool:
        return self.used < self.limit

    def take(self) -> None:
        if not self.allow():
            raise CapError()
        self.used += 1


def positions_url(handle: str) -> str:
    return _url(POSITIONS_PATH, handle)


def following_url(handle: str) -> str:
    return _url(FOLLOWING_PATH, handle)


def get_json(url: str, *, token: str, transport, budget: Budget) -> object:
    """Perform exactly one GET. The budget increments even when the response is an error."""
    if "cursor=" in url or "?cursor" in url:
        raise ProviderError("pagination is disabled; stopped")
    if not url.startswith(f"{API_ORIGIN}/"):
        raise ProviderError("refusing non-provider URL; stopped")
    key = _clean_key(token)
    budget.take()
    try:
        status, body = transport(url, key)
    except ProviderError as exc:
        message = safe_text(exc)
        raise_clean(ProviderError(message))
    except Exception as exc:
        safe_text(exc)
        raise_clean(ProviderError("request failed; stopped"))
    if not isinstance(status, int) or not isinstance(body, (bytes, bytearray)):
        raise_clean(ProviderError("request failed; stopped"))
    if len(body) > MAX_BODY_BYTES:
        raise_clean(ProviderError("response too large; stopped"))
    if status in {401, 403, 402, 429}:
        raise_clean(ProviderStop(status, _code(bytes(body))))
    if status != 200:
        raise_clean(ProviderError(f"HTTP {status}; stopped"))
    try:
        return json.loads(bytes(body).decode("utf-8"), parse_float=Decimal)
    except (UnicodeError, json.JSONDecodeError) as exc:
        safe_text(exc)
        raise_clean(ProviderError("response was not JSON; stopped"))


def urllib_transport(url: str, token: str) -> tuple[int, bytes]:
    if not url.startswith(f"{API_ORIGIN}/"):
        raise ProviderError("refusing non-provider URL; stopped")
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "copytrader-fomo-oneshot",
        },
        method="GET",
    )
    opener = guarded_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.status, response.read(MAX_BODY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        code = exc.code
        try:
            body = exc.read(MAX_BODY_BYTES + 1)
        except Exception:
            body = b""
        safe_text(exc)
        return code, body
    except ProviderError as exc:
        message = safe_text(exc)
        raise_clean(ProviderError(message))
    except Exception as exc:
        safe_text(exc)
        raise_clean(ProviderError("request failed; stopped"))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _stop_redirect(code)

    def http_error_302(self, req, fp, code, msg, headers):
        _stop_redirect(code)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _stop_redirect(code: object) -> None:
    status = code if isinstance(code, int) else 302
    raise_clean(ProviderError(f"HTTP {status} redirect; stopped"))


def _url(template: str, handle: str) -> str:
    safe = quote(normalize_handle(handle), safe="._")
    return API_ORIGIN + template.format(handle=safe)


def _clean_key(token: str) -> str:
    if not isinstance(token, str):
        raise ProviderError("PUMPFOMO_API_KEY is not set")
    key = token.strip()
    if not key:
        raise ProviderError("PUMPFOMO_API_KEY is not set")
    if any(ch in key for ch in "\r\n \t") or key.lower().startswith("bearer "):
        raise ProviderError("PUMPFOMO_API_KEY is not usable")
    return key


def _code(body: bytes) -> str | None:
    try:
        payload = json.loads(body[:8000].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    found = [payload.get("code")]
    error = payload.get("error")
    if isinstance(error, dict):
        found.append(error.get("code"))
    for item in found:
        if isinstance(item, str) and _CODE.fullmatch(item):
            return item
    return None


def _stop_message(status: int, code: str | None) -> str:
    code_bit = f" {code}" if code else ""
    if status == 402:
        return f"HTTP 402{code_bit}; stopped; no upgrade and no top-up"
    return f"HTTP {status}{code_bit}; stopped"
