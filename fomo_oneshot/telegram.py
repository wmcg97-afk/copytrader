"""Owner-only Telegram card. One message, URL button, no buy or sell action."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
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


def send_one(*, token: str, card: Card, transport, chat_id: object = OWNER_CHAT_ID) -> None:
    """Send exactly one message. The caller must not invoke this in a loop."""
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
        status = transport(key, payload)
    except NotifyError as exc:
        message = safe_text(exc)
        raise_clean(NotifyError(message))
    except Exception as exc:
        safe_text(exc)
        raise_clean(NotifyError("telegram request failed"))
    if status != 200:
        raise_clean(NotifyError(f"telegram HTTP {status}; not sent"))


def urllib_send(token: str, payload: dict) -> int:
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
            response.read(65536)
            return response.status
    except urllib.error.HTTPError as exc:
        code = exc.code
        try:
            exc.read(4096)
        except Exception:
            pass
        safe_text(exc)
        return code
    except NotifyError as exc:
        message = safe_text(exc)
        raise_clean(NotifyError(message))
    except Exception as exc:
        safe_text(exc)
        raise_clean(NotifyError("telegram request failed"))


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
