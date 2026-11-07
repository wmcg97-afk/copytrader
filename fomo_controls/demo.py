"""Text samples for review. No network and no Telegram send."""

from __future__ import annotations

import json

from .apply import apply
from .store import bind_menu, new_store, to_dict

OWNER = 8578901453


def transcript() -> str:
    store = new_store()
    parts: list[str] = []

    start = apply(store, _message("/start"))
    parts.append("== owner /start ==")
    parts.append(f"kind: {start.kind}")
    parts.append(f"provider_calls: {start.provider_calls}")
    parts.append(start.text)
    parts.append(_buttons(start.markup))
    bind_menu(store, 10)

    accounts = apply(store, _callback("m:a"))
    parts.append("== owner Accounts edit ==")
    parts.append(f"kind: {accounts.kind} message_id: {accounts.message_id}")
    parts.append(accounts.text)
    parts.append(_buttons(accounts.markup))

    filters = apply(store, _callback("m:f"))
    parts.append("== owner Filters edit ==")
    parts.append(filters.text)

    status = apply(store, _callback("c:resume"))
    parts.append("== owner Resume ==")
    parts.append(status.text)

    before = json.dumps(to_dict(store), sort_keys=True)
    rejected = apply(store, _message("/start", chat_id=111, from_id=111))
    other_chat = apply(store, _callback("a:Y", chat_id=999, from_id=OWNER))
    other_sender = apply(store, _callback("a:Y", chat_id=OWNER, from_id=222))
    injected = apply(store, _callback("a:d:<script>alert(1)</script>"))
    after = json.dumps(to_dict(store), sort_keys=True)
    parts.append("== non-owner and injection ==")
    parts.append(f"other account kind: {rejected.kind} text_empty: {rejected.text == ''}")
    parts.append(f"other chat kind: {other_chat.kind}")
    parts.append(f"other sender kind: {other_sender.kind}")
    parts.append(f"injection kind: {injected.kind}")
    parts.append(f"store_unchanged: {before == after}")
    parts.append(f"provider_calls: {rejected.provider_calls}")
    return "\n".join(parts) + "\n"


def _message(text: str, *, chat_id: int = OWNER, from_id: int = OWNER) -> dict:
    return {
        "message": {
            "message_id": 9,
            "text": text,
            "chat": {"id": chat_id},
            "from": {"id": from_id},
        }
    }


def _callback(data: str, *, chat_id: int = OWNER, from_id: int = OWNER) -> dict:
    return {
        "callback_query": {
            "id": "cb",
            "data": data,
            "from": {"id": from_id},
            "message": {"message_id": 10, "chat": {"id": chat_id}},
        }
    }


def _buttons(markup: dict | None) -> str:
    rows = []
    for row in (markup or {}).get("inline_keyboard", []):
        bits = []
        for button in row:
            if "url" in button:
                bits.append(f"[{button['text']}]({button['url']})")
            else:
                bits.append(f"[{button['text']}|{button.get('callback_data')}]")
        rows.append(" ".join(bits))
    return "\n".join(rows)
