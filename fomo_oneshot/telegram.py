"""Owner-only Telegram card. One message, URL button, no buy or sell action."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from html import escape

from .card import Card
from .constants import HTTP_TIMEOUT_SECONDS, OWNER_CHAT_ID
from .guard import guarded_opener, raise_clean, safe_text
from .redact import redact


class NotifyError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(redact(message))


class OwnerGuard(NotifyError):
    def __init__(self) -> None:
        super().__init__("refusing send: target is not the owner chat")


def assert_owner(chat_id: object) -> int:
    if isinstance(chat_id, bool):
        raise OwnerGuard()
    if isinstance(chat_id, int):
        number = chat_id
    elif isinstance(chat_id, str) and chat_id.strip().isdigit():
        number = int(chat_id.strip())
    else:
        raise OwnerGuard()
    if number != OWNER_CHAT_ID:
        raise OwnerGuard()
    return number


@dataclass(frozen=True)
class SendReceipt:
    """Safe delivery facts only. Never includes the raw Telegram body."""

    confirmed: bool
    message_id: int | None


def interpret_send_response(status: object, body: object) -> SendReceipt:
    """Confirm only HTTP 200, ok true, and a positive integer message_id.

    Anything else is unconfirmed. Callers must not send again because of it.
    """
    if isinstance(status, bool) or not isinstance(status, int) or status != 200:
        return SendReceipt(False, None)
    if not isinstance(body, (bytes, bytearray)):
        return SendReceipt(False, None)
    try:
        payload = json.loads(bytes(body[:65536]).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return SendReceipt(False, None)
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return SendReceipt(False, None)
    result = payload.get("result")
    if not isinstance(result, dict):
        return SendReceipt(False, None)
    message_id = result.get("message_id")
    if isinstance(message_id, bool) or not isinstance(message_id, int) or message_id <= 0:
        return SendReceipt(False, None)
    return SendReceipt(True, message_id)


def send_one(*, token: str, card: Card, transport, chat_id: object = OWNER_CHAT_ID) -> SendReceipt:
    """Send exactly one message. A bad response is unconfirmed and is not retried."""
    chat = assert_owner(chat_id)
    key = _clean_token(token)
    payload = {
        "chat_id": chat,
        "text": _html(card.text),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [[{"text": card.button_text, "url": card.button_url}]]
        },
    }
    try:
        raw = transport(key, payload)
    except NotifyError as exc:
        message = safe_text(exc)
        raise_clean(NotifyError(message))
    except Exception as exc:
        safe_text(exc)
        raise_clean(NotifyError("telegram request failed"))
    status, body = _split_transport_result(raw)
    if isinstance(status, bool) or not isinstance(status, int) or status != 200:
        code = status if isinstance(status, int) and not isinstance(status, bool) else "unknown"
        raise_clean(NotifyError(f"telegram HTTP {code}; not sent"))
    receipt = interpret_send_response(status, body)
    if not receipt.confirmed:
        raise_clean(NotifyError("telegram response unconfirmed; not resent"))
    return receipt


def urllib_send(token: str, payload: dict) -> tuple[int, bytes]:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = guarded_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.status, response.read(65536)
    except urllib.error.HTTPError as exc:
        code = exc.code
        try:
            body = exc.read(4096)
        except Exception:
            body = b""
        safe_text(exc)
        return code, body
    except NotifyError as exc:
        message = safe_text(exc)
        raise_clean(NotifyError(message))
    except Exception as exc:
        safe_text(exc)
        raise_clean(NotifyError("telegram request failed"))


def _split_transport_result(raw: object) -> tuple[object, object]:
    if isinstance(raw, tuple) and len(raw) == 2:
        return raw[0], raw[1]
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw, None
    return None, None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _stop_redirect(code)

    def http_error_302(self, req, fp, code, msg, headers):
        _stop_redirect(code)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _stop_redirect(code: object) -> None:
    status = code if isinstance(code, int) else 302
    raise_clean(NotifyError(f"telegram HTTP {status} redirect; not sent"))


def _clean_token(token: str) -> str:
    if not isinstance(token, str):
        raise NotifyError("TELEGRAM_BOT_TOKEN is not set")
    key = token.strip()
    if not key:
        raise NotifyError("TELEGRAM_BOT_TOKEN is not set")
    if any(ch in key for ch in "\r\n \t"):
        raise NotifyError("TELEGRAM_BOT_TOKEN is not usable")
    return key


def _html(plain: str) -> str:
    lines = plain.split("\n")
    rendered = []
    for index, line in enumerate(lines):
        safe = escape(line, quote=True)
        rendered.append(f"<b>{safe}</b>" if index == 0 else safe)
    return "\n".join(rendered)
