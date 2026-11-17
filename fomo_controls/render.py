"""Plain-text menus and inline keyboards. Callbacks edit one message."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fomo_oneshot.constants import CHAINS, OPEN_FOMO_URL
from fomo_oneshot.links import fomo_url, profile_url
from fomo_oneshot.swap import Swap

from .filters import filter_reasons
from .labels import label
from .store import PAGE_SIZE, Store, Trader

# Names for text only. Coin links still use the four supported chain ids.
_UNLINKED = {143: "Monad", 1: "Ethereum", 5042: "Arc"}
_EMOJI = {1399811149: "◎", 8453: "🔵", 56: "🟡", 4663: "🪶"}


def home_screen(store: Store) -> tuple[str, dict]:
    name = label(store.language, "home_title")
    body = label(store.language, "home_body")
    if store.language == "ru":
        state = "Оповещения: пауза" if store.paused else "Оповещения: предпочтение включено, сборщик не запущен"
    else:
        state = "Alerts: paused" if store.paused else "Alerts: resume preference on, collector not started"
    toggle = "c:pause" if not store.paused else "c:resume"
    toggle_label = label(store.language, "pause") if not store.paused else label(store.language, "resume")
    text = f"{name}\n{body}\n{state}"
    keyboard = [
        [_cb(label(store.language, "accounts"), "m:a"), _cb(label(store.language, "filters"), "m:f")],
        [_cb(label(store.language, "recent"), "m:r"), _cb(label(store.language, "status"), "m:s")],
        [_cb(toggle_label, toggle), _cb(label(store.language, "language"), "m:l")],
    ]
    return text, {"inline_keyboard": keyboard}


def accounts_screen(store: Store) -> tuple[str, dict]:
    matched = _matched(store)
    pages = max(1, (len(matched) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(store.account_page, pages - 1)
    start = page * PAGE_SIZE
    chunk = matched[start:start + PAGE_SIZE]
    lines = [
        label(store.language, "accounts"),
        f"{start + 1 if chunk else 0}-{start + len(chunk)} / {len(matched)}",
    ]
    if store.search:
        lines.append(f"{label(store.language, 'search')}: {store.search}")
    lines.append("Seed source verified-follows-2026-11-07 is not a fresh import.")
    rows = []
    for trader in chunk:
        lines.append(f"@{trader.handle} [{trader.source}]")
        rows.append([
            _url(f"{label(store.language, 'profile')} {trader.handle}", profile_url(trader.handle)),
            _cb(label(store.language, "delete"), f"a:d:{trader.handle}"),
        ])
    nav = []
    if page > 0:
        nav.append(_cb(label(store.language, "prev"), f"a:p:{page - 1}"))
    if start + PAGE_SIZE < len(matched):
        nav.append(_cb(label(store.language, "next"), f"a:p:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([
        _cb(label(store.language, "add"), "a:n"),
        _cb(label(store.language, "search"), "a:q"),
    ])
    rows.append([
        _cb(label(store.language, "delete_all"), "a:D"),
        _cb(label(store.language, "import"), "a:i"),
    ])
    rows.append([
        _cb(label(store.language, "verified"), "a:v"),
        _cb(label(store.language, "back"), "m:h"),
    ])
    return "\n".join(lines), {"inline_keyboard": rows}


def filters_screen(store: Store) -> tuple[str, dict]:
    settings = store.settings
    mcap = "off" if settings.min_mcap_usd is None else str(settings.min_mcap_usd)
    liq = "off" if settings.min_liq_usd is None else str(settings.min_liq_usd)
    holders = "off" if settings.min_holders is None else str(settings.min_holders)
    lines = [
        label(store.language, "filters"),
        f"min trade ${settings.min_trade_usd}",
        f"min mcap ${mcap}",
        f"min liquidity ${liq}",
        "Enrichment is on request for Solana only. No collector.",
        "Unknown market cap or liquidity cannot be passed.",
        "Zero is a real zero, not unknown. FDV is not market cap.",
        "Current DEX data is not the value at the swap time.",
        f"min holders {holders}",
        "Holder counts are not enriched.",
        "sells " + ("on" if settings.show_sells else "off"),
        "breaking detection is not implemented",
        f"stored breaking preference {settings.breaking_traders} traders / {settings.breaking_window_min} min",
        f"requested interval {settings.requested_interval_s}s is not running",
        "No monitoring budget is approved.",
        "silent " + ("on" if settings.silent else "off"),
        "emoji " + ("on" if settings.chain_emoji else "off"),
    ]
    rows = [
        [_cb(label(store.language, "set_trade"), "f:t")],
        [
            _cb(label(store.language, "set_mcap"), "f:c"),
            _cb(label(store.language, "mcap_off" if settings.min_mcap_usd is not None else "mcap_on"), "f:m"),
        ],
        [
            _cb(label(store.language, "set_liq"), "f:l"),
            _cb(label(store.language, "liq_off" if settings.min_liq_usd is not None else "liq_on"), "f:q"),
        ],
        [_cb(label(store.language, "holders"), "f:h")],
        [_cb(label(store.language, "sells"), "f:s"), _cb(label(store.language, "silent"), "f:z")],
        [_cb(label(store.language, "emoji"), "f:e"), _cb(label(store.language, "interval"), "f:i")],
    ]
    network_row = []
    for chain_id, name in CHAINS.items():
        flag = label(store.language, "on") if settings.networks.get(chain_id, False) else label(store.language, "off")
        network_row.append(_cb(f"{name} {flag}", f"f:n:{chain_id}"))
        if len(network_row) == 2:
            rows.append(network_row)
            network_row = []
    if network_row:
        rows.append(network_row)
    rows.append([_cb(label(store.language, "back"), "m:h")])
    return "\n".join(lines), {"inline_keyboard": rows}


def status_screen(store: Store) -> tuple[str, dict]:
    alerts = "paused" if store.paused else "resume preference on, still not polling"
    if store.language == "ru":
        text = "\n".join([
            "Статус",
            "Наблюдение: не запущено",
            "Сборщик: не запущен",
            f"Оповещения: {'пауза' if store.paused else 'предпочтение включено, опрос не идёт'}",
            f"Счета: {len(store.traders)}",
            f"Запрошенный интервал: {store.settings.requested_interval_s} с",
            "Интервал не работает. Бюджет наблюдения не согласован.",
            "Продолжить не запускает опрос и не запускает сборщик.",
            "Последний опрос: никогда",
            "Ключ провайдера: не читался",
            "Кредиты: не читались",
            "Обогащение: только Solana, по запросу. Сборщик не запущен.",
            "Импорт топ-30: недоступен, схема таблицы не проверена",
            "Breaking: не реализовано",
            f"Новым в FOMO? {OPEN_FOMO_URL}",
        ])
    else:
        text = "\n".join([
            "Status",
            "Monitoring: inactive",
            "Collector: not started",
            f"Alerts: {alerts}",
            f"Traders: {len(store.traders)}",
            f"Requested interval: {store.settings.requested_interval_s}s",
            "This interval is not running. No monitoring budget is approved.",
            "Resume does not start polling or a collector.",
            "Last poll: never",
            "Provider key: not read",
            "Credits: not read",
            "Enrichment: Solana only, on request. No collector.",
            "Import top 30: unavailable, leaderboard schema is not verified",
            "Breaking: not implemented",
            f"New to FOMO? {OPEN_FOMO_URL}",
        ])
    return text, {"inline_keyboard": [[_cb(label(store.language, "back"), "m:h")]]}


def recent_screen(store: Store, *, now: datetime) -> tuple[str, dict]:
    rows_data, undated = _recent(store, now)
    pages = max(1, (len(rows_data) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(store.recent_page, pages - 1)
    start = page * PAGE_SIZE
    chunk = rows_data[start:start + PAGE_SIZE]
    lines = [
        f"{label(store.language, 'recent')} {store.recent_hours}h",
        "Cached snapshots only. This screen does not read the provider.",
        f"{start + 1 if chunk else 0}-{start + len(chunk)} / {len(rows_data)}",
    ]
    if undated:
        lines.append(f"{undated} cached swaps had no usable time and were not listed.")
    keyboard = []
    for trader, swap in chunk:
        reasons = filter_reasons(swap, store.settings)
        token = swap.traded_token or "token unknown"
        chain_id = swap.token_network_id
        chain = _chain_text(chain_id, store.settings.chain_emoji)
        amount = swap.usd_in if swap.usd_in is not None else swap.usd_out
        amount_text = "unknown" if amount is None else format(amount, "f")
        lines.append(
            f"@{trader.handle} {swap.side or 'side unknown'} {token} ${amount_text} {chain}"
        )
        if reasons:
            lines.append("blocked: " + ", ".join(reasons))
        if chain_id not in CHAINS:
            lines.append(f"unknown chain {_chain_name(chain_id)}")
        copy_url = fomo_url(swap)
        copy_text = label(store.language, "open") if copy_url == OPEN_FOMO_URL else _copy_label(store, token)
        keyboard.append([
            _url(trader.handle, profile_url(trader.handle)),
            _url(copy_text, copy_url),
        ])
    window_row = [
        _cb("1h", "r:w:1"),
        _cb("6h", "r:w:6"),
        _cb("24h", "r:w:24"),
    ]
    keyboard.append(window_row)
    nav = []
    if page > 0:
        nav.append(_cb(label(store.language, "prev"), f"r:p:{page - 1}"))
    if start + PAGE_SIZE < len(rows_data):
        nav.append(_cb(label(store.language, "next"), f"r:p:{page + 1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([_cb(label(store.language, "back"), "m:h")])
    return "\n".join(lines), {"inline_keyboard": keyboard}


def prompt_screen(store: Store, text: str) -> tuple[str, dict]:
    return text, {"inline_keyboard": [[_cb(label(store.language, "cancel"), "m:h")]]}


def confirm_screen(store: Store, text: str, yes: str, no: str = "a:x") -> tuple[str, dict]:
    return text, {"inline_keyboard": [[
        _cb(label(store.language, "confirm"), yes),
        _cb(label(store.language, "cancel"), no),
    ]]}


def _matched(store: Store) -> list[Trader]:
    query = store.search.casefold()
    if not query:
        return list(store.traders)
    return [trader for trader in store.traders if query in trader.handle.casefold()]


def _recent(store: Store, now: datetime) -> tuple[list[tuple[Trader, Swap]], int]:
    window = timedelta(hours=store.recent_hours)
    found: list[tuple[datetime, Trader, Swap]] = []
    undated = 0
    for trader in store.traders:
        for row in trader.cached:
            swap = _swap_from_row(row)
            parsed = _time(swap.created_at)
            if parsed is None:
                undated += 1
                continue
            if now - window <= parsed <= now + timedelta(seconds=1):
                found.append((parsed, trader, swap))
    found.sort(key=lambda item: item[0], reverse=True)
    return [(trader, swap) for _, trader, swap in found], undated


def _swap_from_row(row: dict) -> Swap:
    side = row.get("side")
    return Swap(
        id=row.get("id") if isinstance(row.get("id"), str) else None,
        side=side if side in {"buy", "sell"} else None,
        created_at=row.get("created_at") if isinstance(row.get("created_at"), str) else None,
        provider=row.get("provider") if isinstance(row.get("provider"), str) else None,
        network_id=_int(row.get("network_id")),
        in_network_id=_int(row.get("in_network_id")),
        out_network_id=_int(row.get("out_network_id")),
        in_token=_text(row.get("in_token")),
        out_token=_text(row.get("out_token")),
        in_amount=None,
        out_amount=None,
        usd_in=_decimal(row.get("usd_in")),
        usd_out=_decimal(row.get("usd_out")),
        price=None,
        is_off_platform=None,
        is_crossmint=None,
        address=None,
        recipient=None,
        in_trade_id=None,
        out_trade_id=None,
    )


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _chain_name(chain_id: int | None) -> str:
    if chain_id is None:
        return "unknown"
    if chain_id in CHAINS:
        return CHAINS[chain_id]
    return _UNLINKED.get(chain_id, str(chain_id))


def _chain_text(chain_id: int | None, emoji: bool) -> str:
    name = _chain_name(chain_id)
    mark = _EMOJI.get(chain_id or -1, "")
    if emoji and mark:
        return f"{mark} {name}"
    return name


def _copy_label(store: Store, token: str) -> str:
    prefix = label(store.language, "copy")
    text = f"{prefix} {token}"
    if len(text) <= 64:
        return text
    return prefix


def _cb(text: str, data: str) -> dict:
    return {"text": text[:64], "callback_data": data}


def _url(text: str, href: str) -> dict:
    return {"text": text[:64], "url": href}


def _int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _text(value: object) -> str | None:
    if not isinstance(value, str) or not value or any(ch in value for ch in "\r\n"):
        return None
    return value


def _decimal(value: object) -> Decimal | None:
    if not isinstance(value, str):
        return None
    try:
        number = Decimal(value)
    except Exception:
        return None
    if not number.is_finite():
        return None
    return number
