"""Offline account and filter state. This is not the desk database."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from fomo_oneshot.seen import SeenError, assert_safe_seen_path
from fomo_oneshot.swap import Swap, is_swap_id, normalize_handle, parse_positions

VERIFIED_FOLLOWS = (
    "PressingProfits",
    "bystevenr",
    "escobarpablo",
    "savipww",
)
VERIFIED_SOURCE = "verified-follows-2026-11-07"
OWNER_ADDED = "owner-added"
PAGE_SIZE = 10
MAX_TRADERS = 100
MAX_SEEN = 1000
NETWORK_IDS = (1399811149, 4663, 8453, 56)


class ControlsError(Exception):
    pass


@dataclass
class Settings:
    min_trade_usd: int = 50
    min_mcap_usd: int | None = 50_000
    min_liq_usd: int | None = 20_000
    mcap_amount_usd: int = 50_000
    liq_amount_usd: int = 20_000
    min_holders: int | None = None
    networks: dict[int, bool] = field(default_factory=lambda: {item: True for item in NETWORK_IDS})
    show_sells: bool = True
    requested_interval_s: int = 20
    breaking_traders: int = 3
    breaking_window_min: int = 30
    chain_emoji: bool = True
    silent: bool = False
    import_min_trades: int = 20
    import_window: str = "both"


@dataclass
class Trader:
    handle: str
    source: str
    seeded: bool = False
    seen_ids: list[str] = field(default_factory=list)
    cached: list[dict] = field(default_factory=list)


@dataclass
class Store:
    paused: bool = True
    language: str = "en"
    menu_message_id: int | None = None
    awaiting: str | None = None
    search: str = ""
    recent_hours: int = 24
    account_page: int = 0
    recent_page: int = 0
    traders: list[Trader] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)

    def find(self, handle: str) -> Trader | None:
        key = handle.casefold()
        for trader in self.traders:
            if trader.handle.casefold() == key:
                return trader
        return None


def new_store() -> Store:
    """Start paused, with the four previously verified follows as seed choices.

    The source label is the 2026-11-07 follow list. This is not a live import.
    """
    traders = [
        Trader(handle=handle, source=VERIFIED_SOURCE)
        for handle in VERIFIED_FOLLOWS
    ]
    return Store(traders=traders)


def bind_menu(store: Store, message_id: object) -> bool:
    if isinstance(message_id, bool) or not isinstance(message_id, int) or message_id <= 0:
        return False
    store.menu_message_id = message_id
    return True


def seed_snapshot(store: Store, handle: str, payload: object) -> dict:
    """Mark injected swap ids seen and cache them. Does not call the provider or send."""
    try:
        normalized = normalize_handle(handle)
    except ValueError as exc:
        raise ControlsError(str(exc)) from exc
    trader = store.find(normalized)
    if trader is None:
        raise ControlsError("trader is not on the account list")
    page = parse_positions(payload)
    if page.note:
        raise ControlsError(page.note)
    added = 0
    for swap in page.swaps:
        if not swap.id:
            continue
        if swap.id not in trader.seen_ids:
            if len(trader.seen_ids) < MAX_SEEN:
                trader.seen_ids.append(swap.id)
                added += 1
        _cache(trader, swap)
    trader.seeded = True
    return {"handle": trader.handle, "new_ids": added, "sends": 0, "provider_calls": 0, "seeded": True}


def save_store(path: Path, store: Store) -> None:
    assert_safe_seen_path(path)
    if path.name in {"state.json", "activity.json", "chart.json"}:
        raise SeenError("controls store cannot use a published desk filename")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(to_dict(store), indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)


def load_store(path: Path) -> Store:
    assert_safe_seen_path(path)
    if not path.exists():
        return new_store()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ControlsError("controls store unreadable") from exc
    return from_dict(payload)


def to_dict(store: Store) -> dict:
    return {
        "version": 1,
        "paused": store.paused,
        "language": store.language,
        "menu_message_id": store.menu_message_id,
        "awaiting": store.awaiting,
        "search": store.search,
        "recent_hours": store.recent_hours,
        "account_page": store.account_page,
        "recent_page": store.recent_page,
        "monitoring": "inactive",
        "settings": _settings_dict(store.settings),
        "traders": [
            {
                "handle": trader.handle,
                "source": trader.source,
                "seeded": trader.seeded,
                "seen_ids": list(trader.seen_ids),
                "cached": list(trader.cached),
            }
            for trader in store.traders
        ],
    }


def from_dict(payload: object) -> Store:
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ControlsError("controls store unreadable")
    if payload.get("monitoring") not in {None, "inactive"}:
        raise ControlsError("controls store unreadable")
    store = Store()
    store.paused = payload.get("paused") if isinstance(payload.get("paused"), bool) else True
    language = payload.get("language")
    store.language = language if language in {"en", "ru"} else "en"
    menu_id = payload.get("menu_message_id")
    store.menu_message_id = menu_id if isinstance(menu_id, int) and not isinstance(menu_id, bool) and menu_id > 0 else None
    awaiting = payload.get("awaiting")
    store.awaiting = awaiting if awaiting in {None, "add", "search", "min_trade", "min_mcap", "min_liq", "min_holders", "interval"} else None
    search = payload.get("search")
    store.search = search if isinstance(search, str) and len(search) <= 32 else ""
    hours = payload.get("recent_hours")
    store.recent_hours = hours if hours in {1, 6, 24} else 24
    store.account_page = _page(payload.get("account_page"))
    store.recent_page = _page(payload.get("recent_page"))
    store.settings = _settings_from(payload.get("settings"))
    traders = payload.get("traders")
    if not isinstance(traders, list):
        raise ControlsError("controls store unreadable")
    for item in traders[:MAX_TRADERS]:
        trader = _trader_from(item)
        if trader and store.find(trader.handle) is None:
            store.traders.append(trader)
    return store


def add_handles(store: Store, handles: list[str], *, source: str) -> tuple[list[str], list[str]]:
    added: list[str] = []
    skipped: list[str] = []
    for handle in handles:
        if store.find(handle) is not None:
            skipped.append(handle)
            continue
        if len(store.traders) >= MAX_TRADERS:
            skipped.append(handle)
            continue
        store.traders.append(Trader(handle=handle, source=source))
        added.append(handle)
    return added, skipped


def add_verified_missing(store: Store) -> list[str]:
    return add_handles(store, list(VERIFIED_FOLLOWS), source=VERIFIED_SOURCE)[0]


def _cache(trader: Trader, swap: Swap) -> None:
    row = {
        "id": swap.id,
        "side": swap.side,
        "created_at": swap.created_at,
        "in_token": swap.in_token,
        "out_token": swap.out_token,
        "network_id": swap.network_id,
        "in_network_id": swap.in_network_id,
        "out_network_id": swap.out_network_id,
        "usd_in": None if swap.usd_in is None else format(swap.usd_in, "f"),
        "usd_out": None if swap.usd_out is None else format(swap.usd_out, "f"),
        "provider": swap.provider,
    }
    trader.cached = [item for item in trader.cached if item.get("id") != swap.id]
    trader.cached.insert(0, row)
    del trader.cached[50:]


def _page(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _settings_dict(settings: Settings) -> dict:
    return {
        "min_trade_usd": settings.min_trade_usd,
        "min_mcap_usd": settings.min_mcap_usd,
        "min_liq_usd": settings.min_liq_usd,
        "mcap_amount_usd": settings.mcap_amount_usd,
        "liq_amount_usd": settings.liq_amount_usd,
        "min_holders": settings.min_holders,
        "networks": {str(key): value for key, value in settings.networks.items()},
        "show_sells": settings.show_sells,
        "requested_interval_s": settings.requested_interval_s,
        "breaking_traders": settings.breaking_traders,
        "breaking_window_min": settings.breaking_window_min,
        "chain_emoji": settings.chain_emoji,
        "silent": settings.silent,
        "import_min_trades": settings.import_min_trades,
        "import_window": settings.import_window,
    }


def _settings_from(payload: object) -> Settings:
    settings = Settings()
    if not isinstance(payload, dict):
        return settings
    settings.min_trade_usd = _bounded(payload.get("min_trade_usd"), 0, 1_000_000_000, 50)
    settings.min_mcap_usd = _optional(payload.get("min_mcap_usd"), 1_000_000_000_000)
    settings.min_liq_usd = _optional(payload.get("min_liq_usd"), 1_000_000_000_000)
    if "mcap_amount_usd" in payload:
        settings.mcap_amount_usd = _bounded(payload.get("mcap_amount_usd"), 0, 1_000_000_000_000, 50_000)
    elif isinstance(payload.get("min_mcap_usd"), int) and not isinstance(payload.get("min_mcap_usd"), bool):
        settings.mcap_amount_usd = _bounded(payload.get("min_mcap_usd"), 0, 1_000_000_000_000, 50_000)
    if "liq_amount_usd" in payload:
        settings.liq_amount_usd = _bounded(payload.get("liq_amount_usd"), 0, 1_000_000_000_000, 20_000)
    elif isinstance(payload.get("min_liq_usd"), int) and not isinstance(payload.get("min_liq_usd"), bool):
        settings.liq_amount_usd = _bounded(payload.get("min_liq_usd"), 0, 1_000_000_000_000, 20_000)
    settings.min_holders = _optional(payload.get("min_holders"), 1_000_000_000)
    networks = {item: True for item in NETWORK_IDS}
    raw = payload.get("networks")
    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                chain = int(key)
            except (TypeError, ValueError):
                continue
            if chain in networks and isinstance(value, bool):
                networks[chain] = value
    settings.networks = networks
    if isinstance(payload.get("show_sells"), bool):
        settings.show_sells = payload["show_sells"]
    settings.requested_interval_s = _bounded(payload.get("requested_interval_s"), 20, 86_400, 20)
    settings.breaking_traders = _bounded(payload.get("breaking_traders"), 2, 20, 3)
    settings.breaking_window_min = _bounded(payload.get("breaking_window_min"), 5, 24 * 60, 30)
    if isinstance(payload.get("chain_emoji"), bool):
        settings.chain_emoji = payload["chain_emoji"]
    if isinstance(payload.get("silent"), bool):
        settings.silent = payload["silent"]
    settings.import_min_trades = _bounded(payload.get("import_min_trades"), 1, 10_000, 20)
    if payload.get("import_window") in {"7d", "30d", "both"}:
        settings.import_window = payload["import_window"]
    return settings


def _trader_from(payload: object) -> Trader | None:
    if not isinstance(payload, dict):
        return None
    try:
        handle = normalize_handle(str(payload.get("handle", "")))
    except ValueError:
        return None
    source = payload.get("source")
    if source not in {VERIFIED_SOURCE, OWNER_ADDED}:
        source = OWNER_ADDED
    seen: list[str] = []
    raw_ids = payload.get("seen_ids")
    if isinstance(raw_ids, list):
        for item in raw_ids:
            if is_swap_id(item) and item not in seen:
                seen.append(item)
            if len(seen) >= MAX_SEEN:
                break
    cached: list[dict] = []
    raw_cached = payload.get("cached")
    if isinstance(raw_cached, list):
        for item in raw_cached[:50]:
            if isinstance(item, dict) and is_swap_id(item.get("id")):
                cached.append({key: item.get(key) for key in (
                    "id", "side", "created_at", "in_token", "out_token", "network_id",
                    "in_network_id", "out_network_id", "usd_in", "usd_out", "provider",
                )})
    return Trader(
        handle=handle,
        source=source,
        seeded=payload.get("seeded") is True,
        seen_ids=seen,
        cached=cached,
    )


def _bounded(value: object, low: int, high: int, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    if value < low or value > high:
        return default
    return value


def _optional(value: object, high: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > high:
        return None
    return value
