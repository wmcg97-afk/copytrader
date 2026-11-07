"""Owner-only Telegram card. One message, URL button, no buy or sell action."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from html import escape

from .card import Card
from .constants import HTTP_TIMEOUT_SECONDS, OWNER_CHAT_ID
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
    try:
        number = int(chat_id)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise OwnerGuard() from exc
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
    except NotifyError:
        raise
    except Exception as exc:
        raise NotifyError("telegram request failed") from exc
    if status != 200:
        raise NotifyError(f"telegram HTTP {status}; not sent")


def urllib_send(token: str, payload: dict) -> int:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            response.read(65536)
            return response.status
    except urllib.error.HTTPError as exc:
        try:
            exc.read(4096)
        except Exception:
            pass
        return exc.code
    except NotifyError:
        raise
    except Exception as exc:
        raise NotifyError("telegram request failed") from exc


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise NotifyError(f"telegram HTTP {code} redirect; not sent")


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
