"""Apply one injected Telegram update. This does not poll or call a provider."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from fomo_oneshot.constants import CHAINS, OWNER_CHAT_ID
from fomo_oneshot.swap import normalize_handle
from fomo_oneshot.telegram import OwnerGuard, assert_owner

from .labels import label
from .render import (
    accounts_screen,
    confirm_screen,
    filters_screen,
    home_screen,
    prompt_screen,
    recent_screen,
    status_screen,
)
from .store import OWNER_ADDED, Store, add_handles, add_verified_missing

_CALLBACK = re.compile(r"^[A-Za-z0-9:._-]{1,64}$")
_NUMBER = re.compile(r"^[0-9]{1,10}$")
_SEARCH = re.compile(r"^[A-Za-z0-9_.]{0,32}$")


@dataclass(frozen=True)
class Effect:
    kind: str
    text: str = ""
    markup: dict | None = None
    message_id: int | None = None
    chat_id: int | None = None
    provider_calls: int = 0


def apply(store: Store, update: object, *, now: datetime | None = None) -> Effect:
    parsed = _parse(update)
    if parsed is None or not _authorized(parsed[0], parsed[1]):
        return Effect("ignore")
    chat_id, from_id, kind, payload, message_id = parsed
    del from_id
    moment = now or datetime.now(timezone.utc)
    if kind == "callback":
        if message_id is None or not _CALLBACK.fullmatch(payload):
            return Effect("ignore")
        text, markup = _callback(store, payload, moment)
        if text is None:
            return Effect("ignore")
        return Effect("edit", text=text, markup=markup, message_id=message_id, chat_id=chat_id)
    text, markup, mode = _message(store, payload, moment)
    if mode == "edit" and store.menu_message_id is not None:
        return Effect("edit", text=text, markup=markup, message_id=store.menu_message_id, chat_id=chat_id)
    return Effect("send", text=text, markup=markup, chat_id=chat_id)


def _callback(store: Store, data: str, now: datetime) -> tuple[str | None, dict | None]:
    parts = data.split(":")
    head = parts[0]
    if head == "m" and len(parts) == 2:
        return _menu(store, parts[1], now)
    if head == "c" and len(parts) == 2:
        return _run_toggle(store, parts[1])
    if head == "l" and len(parts) == 2 and parts[1] in {"en", "ru"}:
        store.language = parts[1]
        store.awaiting = None
        return home_screen(store)
    if head == "a":
        return _accounts(store, parts)
    if head == "f":
        return _filters(store, parts)
    if head == "r":
        return _recent(store, parts, now)
    return None, None


def _menu(store: Store, code: str, now: datetime) -> tuple[str | None, dict | None]:
    store.awaiting = None
    if code == "h":
        return home_screen(store)
    if code == "a":
        return accounts_screen(store)
    if code == "f":
        return filters_screen(store)
    if code == "r":
        return recent_screen(store, now=now)
    if code == "s":
        return status_screen(store)
    if code == "l":
        back = label(store.language, "back")
        return "EN / RU", {"inline_keyboard": [[
            {"text": "EN", "callback_data": "l:en"},
            {"text": "RU", "callback_data": "l:ru"},
        ], [{"text": back, "callback_data": "m:h"}]]}
    return None, None


def _run_toggle(store: Store, code: str) -> tuple[str | None, dict | None]:
    if code == "pause":
        store.paused = True
        return status_screen(store)
    if code == "resume":
        store.paused = False
        return status_screen(store)
    return None, None


def _accounts(store: Store, parts: list[str]) -> tuple[str | None, dict | None]:
    if len(parts) == 2 and parts[1] == "n":
        store.awaiting = "add"
        return prompt_screen(store, "Send handles separated by commas or new lines. @ is optional.")
    if len(parts) == 2 and parts[1] == "q":
        store.awaiting = "search"
        return prompt_screen(store, "Send a handle fragment. Letters, digits, _ and . only.")
    if len(parts) == 2 and parts[1] == "x":
        store.awaiting = None
        return accounts_screen(store)
    if len(parts) == 2 and parts[1] == "D":
        return confirm_screen(
            store,
            f"Delete all {len(store.traders)} accounts? Nothing is deleted yet.",
            "a:Y",
        )
    if len(parts) == 2 and parts[1] == "Y":
        store.traders.clear()
        store.account_page = 0
        return accounts_screen(store)
    if len(parts) == 2 and parts[1] == "i":
        return prompt_screen(
            store,
            "Import top 30 is unavailable. The leaderboard response schema is not verified. No request was made.",
        )
    if len(parts) == 2 and parts[1] == "v":
        added = add_verified_missing(store)
        screen, markup = accounts_screen(store)
        note = "Added from the previously verified follow list. Not a fresh import."
        if not added:
            note = "Verified follows are already listed. Not a fresh import."
        return f"{note}\n{screen}", markup
    if len(parts) == 3 and parts[1] == "p" and parts[2].isdigit():
        store.account_page = int(parts[2])
        return accounts_screen(store)
    if len(parts) == 3 and parts[1] in {"d", "y"}:
        try:
            handle = normalize_handle(parts[2])
        except ValueError:
            return None, None
        if parts[1] == "d":
            if store.find(handle) is None:
                return accounts_screen(store)
            return confirm_screen(store, f"Delete @{handle}? Nothing is deleted yet.", f"a:y:{handle}")
        trader = store.find(handle)
        if trader is not None:
            store.traders = [item for item in store.traders if item is not trader]
        return accounts_screen(store)
    return None, None


def _filters(store: Store, parts: list[str]) -> tuple[str | None, dict | None]:
    settings = store.settings
    if len(parts) == 2 and parts[1] == "t":
        store.awaiting = "min_trade"
        return prompt_screen(store, "Send a whole number of USD for the minimum trade.")
    if len(parts) == 2 and parts[1] == "c":
        store.awaiting = "min_mcap"
        return prompt_screen(store, "Send a whole USD market cap. This does not start a lookup.")
    if len(parts) == 2 and parts[1] == "l":
        store.awaiting = "min_liq"
        return prompt_screen(store, "Send a whole USD liquidity. This does not start a lookup.")
    if len(parts) == 2 and parts[1] == "h":
        store.awaiting = "min_holders"
        return prompt_screen(store, "Send a whole number, or off. Holder counts are not in swaps.")
    if len(parts) == 2 and parts[1] == "i":
        store.awaiting = "interval"
        return prompt_screen(store, "Send a requested interval in seconds. It will not start polling.")
    if len(parts) == 2 and parts[1] == "m":
        if settings.min_mcap_usd is None:
            settings.min_mcap_usd = settings.mcap_amount_usd
        else:
            settings.min_mcap_usd = None
        return filters_screen(store)
    if len(parts) == 2 and parts[1] == "q":
        if settings.min_liq_usd is None:
            settings.min_liq_usd = settings.liq_amount_usd
        else:
            settings.min_liq_usd = None
        return filters_screen(store)
    if len(parts) == 2 and parts[1] == "s":
        settings.show_sells = not settings.show_sells
        return filters_screen(store)
    if len(parts) == 2 and parts[1] == "z":
        settings.silent = not settings.silent
        return filters_screen(store)
    if len(parts) == 2 and parts[1] == "e":
        settings.chain_emoji = not settings.chain_emoji
        return filters_screen(store)
    if len(parts) == 3 and parts[1] == "n" and parts[2].isdigit():
        chain = int(parts[2])
        if chain not in CHAINS:
            return None, None
        settings.networks[chain] = not settings.networks.get(chain, False)
        return filters_screen(store)
    return None, None


def _recent(store: Store, parts: list[str], now: datetime) -> tuple[str | None, dict | None]:
    if len(parts) == 3 and parts[1] == "w" and parts[2] in {"1", "6", "24"}:
        store.recent_hours = int(parts[2])
        store.recent_page = 0
        return recent_screen(store, now=now)
    if len(parts) == 3 and parts[1] == "p" and parts[2].isdigit():
        store.recent_page = int(parts[2])
        return recent_screen(store, now=now)
    return None, None


def _message(store: Store, text: str, now: datetime) -> tuple[str, dict, str]:
    if len(text) > 2000:
        screen, markup = home_screen(store)
        return f"Input was too long and was not saved.\n{screen}", markup, "edit"
    stripped = text.strip()
    if stripped == "/start":
        store.awaiting = None
        screen, markup = home_screen(store)
        return screen, markup, "edit" if store.menu_message_id else "send"
    if stripped == "/pause":
        store.paused = True
        screen, markup = status_screen(store)
        return screen, markup, "edit"
    if stripped == "/resume":
        store.paused = False
        screen, markup = status_screen(store)
        return screen, markup, "edit"
    if stripped.startswith("/add"):
        return _add_text(store, stripped[4:])
    if stripped.startswith("/search"):
        return _search_text(store, stripped[7:].strip())
    if store.awaiting == "add":
        return _add_text(store, stripped)
    if store.awaiting == "search":
        return _search_text(store, stripped)
    if store.awaiting == "min_trade":
        number = _number(stripped)
        if number is None or number > 1_000_000_000:
            return prompt_screen(store, "Minimum trade was not a whole number of USD. Nothing was saved.") + ("edit",)  # type: ignore[operator]
        store.settings.min_trade_usd = number
        store.awaiting = None
        screen, markup = filters_screen(store)
        return screen, markup, "edit"
    if store.awaiting == "min_mcap":
        return _set_threshold(store, stripped, "mcap")
    if store.awaiting == "min_liq":
        return _set_threshold(store, stripped, "liq")
    if store.awaiting == "min_holders":
        if stripped.casefold() in {"off", "выкл"}:
            store.settings.min_holders = None
        else:
            number = _number(stripped)
            if number is None:
                return (*prompt_screen(store, "Holders value was not saved."), "edit")
            store.settings.min_holders = number
        store.awaiting = None
        screen, markup = filters_screen(store)
        return screen, markup, "edit"
    if store.awaiting == "interval":
        number = _number(stripped)
        if number is None or number > 86_400:
            return (*prompt_screen(store, "Interval was not saved. Polling was not started."), "edit")
        store.settings.requested_interval_s = max(20, number)
        store.awaiting = None
        screen, markup = filters_screen(store)
        note = "Requested interval saved. It is not running. No monitoring budget is approved."
        return f"{note}\n{screen}", markup, "edit"
    screen, markup = home_screen(store)
    return f"Unrecognized. Nothing was changed.\n{screen}", markup, "edit"


def _add_text(store: Store, text: str) -> tuple[str, dict, str]:
    good, bad = _split_handles(text)
    added, skipped = add_handles(store, good, source=OWNER_ADDED)
    store.awaiting = None
    screen, markup = accounts_screen(store)
    note = f"Added {len(added)}. Skipped {len(skipped)}. Invalid {len(bad)}."
    return f"{note}\n{screen}", markup, "edit"


def _search_text(store: Store, text: str) -> tuple[str, dict, str]:
    if not _SEARCH.fullmatch(text):
        screen, markup = prompt_screen(store, "Search was not saved.")
        return screen, markup, "edit"
    store.search = text
    store.account_page = 0
    store.awaiting = None
    screen, markup = accounts_screen(store)
    return screen, markup, "edit"


def _set_threshold(store: Store, text: str, kind: str) -> tuple[str, dict, str]:
    number = _amount(text)
    if number is None:
        screen, markup = prompt_screen(store, "Threshold was not a whole number of USD. Nothing was saved. No lookup was started.")
        return screen, markup, "edit"
    if kind == "mcap":
        store.settings.mcap_amount_usd = number
        store.settings.min_mcap_usd = number
    else:
        store.settings.liq_amount_usd = number
        store.settings.min_liq_usd = number
    store.awaiting = None
    screen, markup = filters_screen(store)
    return f"Saved ${number}. Solana enrichment stays on request. No collector.\n{screen}", markup, "edit"


def _amount(text: str) -> int | None:
    if not re.fullmatch(r"^[0-9]{1,13}$", text):
        return None
    number = int(text)
    if number > 1_000_000_000_000:
        return None
    return number


def _split_handles(text: str) -> tuple[list[str], list[str]]:
    good: list[str] = []
    bad: list[str] = []
    for chunk in re.split(r"[\s,]+", text.strip()):
        if chunk in {"", "/add"}:
            continue
        try:
            handle = normalize_handle(chunk)
        except ValueError:
            bad.append(chunk[:32])
            continue
        if handle not in good:
            good.append(handle)
    return good, bad


def _number(text: str) -> int | None:
    if not _NUMBER.fullmatch(text):
        return None
    return int(text)


def _parse(update: object) -> tuple[object, object, str, str, int | None] | None:
    if not isinstance(update, dict):
        return None
    if "callback_query" in update:
        query = update.get("callback_query")
        if not isinstance(query, dict):
            return None
        sender = query.get("from") if isinstance(query.get("from"), dict) else {}
        message = query.get("message") if isinstance(query.get("message"), dict) else {}
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        data = query.get("data")
        if not isinstance(data, str):
            return None
        return chat.get("id"), sender.get("id"), "callback", data, _message_id(message.get("message_id"))
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    text = message.get("text")
    if not isinstance(text, str):
        return None
    return chat.get("id"), sender.get("id"), "message", text, _message_id(message.get("message_id"))


def _message_id(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _authorized(chat_id: object, from_id: object) -> bool:
    try:
        return assert_owner(chat_id) == OWNER_CHAT_ID and assert_owner(from_id) == OWNER_CHAT_ID
    except OwnerGuard:
        return False
