"""Route /fomo through the existing desk consumer. Does not poll or call a provider."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fomo_oneshot.constants import OWNER_CHAT_ID
from fomo_oneshot.telegram import interpret_send_response

from .apply import apply
from .store import Store, load_store, new_store, save_store

_FOMO_CALLBACK = re.compile(r"^[A-Za-z0-9:._-]{1,64}$")
_FOMO_HEADS = {"m", "c", "l", "a", "f", "r"}


def classify_text(raw: str, *, awaiting: str | None) -> str:
    """Return fomo, desk, or desk_help. Desk commands always win."""
    if _is_desk_command(raw):
        return "desk"
    low = raw.lower()
    if low == "fomo" or low.startswith("fomo "):
        return "fomo"
    if awaiting:
        return "fomo"
    return "desk_help"


def classify_callback(data: str) -> str:
    if data.startswith("bought:") or data.startswith("sold:"):
        return "desk_trade"
    if _FOMO_CALLBACK.fullmatch(data or "") and data.split(":", 1)[0] in _FOMO_HEADS:
        return "fomo"
    return "desk_other"


def controls_text(raw: str) -> str:
    low = raw.lower()
    if low == "fomo":
        return "/start"
    if low.startswith("fomo "):
        rest = raw.split(None, 1)[1].strip()
        if rest.startswith("/"):
            return rest
        return "/" + rest
    return raw


class DeskFomoHook:
    """One in-memory menu store for the single desk Telegram task."""

    def __init__(self, store_path: Path, http, token_fn, owner_fn):
        self.store_path = Path(store_path)
        self.http = http
        self.token_fn = token_fn
        self.owner_fn = owner_fn
        self.store = self._load()

    async def maybe_text(self, raw: str, chat_id, from_id) -> bool:
        kind = classify_text(raw, awaiting=self.store.awaiting)
        if kind != "fomo":
            return False
        if not self._allowed(chat_id, from_id):
            return True
        effect = apply(self.store, _message_update(controls_text(raw), chat_id, from_id))
        self._save()
        await self._deliver(effect)
        return True

    async def maybe_callback(self, cq: dict, data: str, chat_id, from_id) -> bool:
        if classify_callback(data) != "fomo":
            return False
        if not self._allowed(chat_id, from_id):
            return True
        callback_id = cq.get("id") if isinstance(cq, dict) else None
        await self._answer(callback_id)
        effect = apply(self.store, {"callback_query": cq})
        self._save()
        await self._deliver(effect)
        return True

    def _allowed(self, chat_id, from_id) -> bool:
        try:
            desk_owner = int(self.owner_fn() or 0)
            chat_ok = int(chat_id) == OWNER_CHAT_ID
            sender_ok = int(from_id) == OWNER_CHAT_ID
        except (TypeError, ValueError):
            return False
        return desk_owner == OWNER_CHAT_ID and chat_ok and sender_ok

    def _load(self) -> Store:
        try:
            return load_store(self.store_path)
        except Exception:
            return new_store()

    def _save(self) -> None:
        try:
            save_store(self.store_path, self.store)
        except Exception:
            return

    async def _answer(self, callback_id) -> None:
        if not callback_id:
            return
        await self._post("answerCallbackQuery", {"callback_query_id": callback_id})

    async def _deliver(self, effect) -> None:
        if effect.kind == "ignore" or effect.provider_calls:
            return
        payload = {
            "chat_id": OWNER_CHAT_ID,
            "text": effect.text,
            "disable_web_page_preview": True,
        }
        if effect.markup:
            payload["reply_markup"] = effect.markup
        if self.store.settings.silent:
            payload["disable_notification"] = True
        if effect.kind == "edit" and effect.message_id:
            payload["message_id"] = effect.message_id
            response = await self._post("editMessageText", payload)
            interpret_send_response(_status(response), _body(response))
            return
        if effect.kind == "send":
            response = await self._post("sendMessage", payload)
            receipt = interpret_send_response(_status(response), _body(response))
            if receipt.confirmed and receipt.message_id:
                from .store import bind_menu
                bind_menu(self.store, receipt.message_id)
                self._save()
            return

    async def _post(self, method: str, payload: dict):
        token = ""
        try:
            token = self.token_fn() or ""
        except Exception:
            token = ""
        if not token or any(ch in token for ch in "\r\n \t"):
            return None
        try:
            return await self.http.post(
                f"https://api.telegram.org/bot{token}/{method}",
                json=payload,
                timeout=20,
                follow_redirects=False,
            )
        except TypeError:
            try:
                return await self.http.post(
                    f"https://api.telegram.org/bot{token}/{method}",
                    json=payload,
                    timeout=20,
                )
            except Exception:
                return None
        except Exception:
            return None


def _message_update(text: str, chat_id, from_id) -> dict:
    return {
        "message": {
            "message_id": 1,
            "text": text,
            "chat": {"id": chat_id},
            "from": {"id": from_id},
        }
    }


def _status(response) -> int | None:
    if response is None:
        return None
    code = getattr(response, "status_code", None)
    if isinstance(code, int) and not isinstance(code, bool):
        return code
    return None


def _body(response) -> bytes:
    if response is None:
        return b""
    try:
        payload = response.json()
    except Exception:
        return b""
    if not isinstance(payload, dict):
        return b""
    try:
        return json.dumps(payload).encode("utf-8")
    except (TypeError, ValueError):
        return b""


def _is_desk_command(raw: str) -> bool:
    low = raw.lower()
    if low in {"start", "help", "status", "invite", "report", "paper", "live"}:
        return True
    if raw.strip() == "LIVE":
        return True
    if re.match(r"pause\s+\w+$", low):
        return True
    if re.match(r"resume\s+\w+$", low):
        return True
    if re.match(r"stack\s+[0-9]+(?:\.[0-9]+)?$", low):
        return True
    if low.startswith("set "):
        return True
    if re.match(r"(buy|sell|why)\s+.+$", raw, re.I):
        return True
    return False
