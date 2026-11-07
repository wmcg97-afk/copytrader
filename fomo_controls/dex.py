"""On-demand DEX Screener market data. No scheduler and no watcher loop.

Only Solana is enabled. The public sample was fetched 2026-11-07T19:46:18Z.
That clock is when the HTTP response was observed. It is not a chain update
time and it is not the Nov 6 swap time. FDV is never copied into market cap.
Zero is a real number. Missing, null, non-numeric, non-finite, and negative
values are unknown.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import quote

from fomo_oneshot.guard import guarded_opener, raise_clean, safe_text
from fomo_oneshot.swap import Swap

SOLANA_NETWORK_ID = 1399811149
DEX_CHAIN = {SOLANA_NETWORK_ID: "solana"}
BASE_URL = "https://api.dexscreener.com"
MIN_CACHE_SECONDS = 30
DEFAULT_MAX_AGE_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 15
MAX_BODY_BYTES = 1_000_000
MAX_PAIRS = 100
_SOLANA = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_EVM = re.compile(r"^0x[0-9a-fA-F]{40}$")


class DexError(Exception):
    def __init__(self, message: str = "dex request failed; stopped") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class MarketSnapshot:
    provider: str
    pair_address: str | None
    chain: str | None
    token: str
    network_id: int
    fetched_at: datetime
    market_cap: Decimal | None
    liquidity_usd: Decimal | None
    fdv: Decimal | None
    coverage: str

    def age_seconds(self, now: datetime) -> int:
        return max(0, int((now - self.fetched_at).total_seconds()))


@dataclass
class MarketCache:
    min_hold_seconds: int = MIN_CACHE_SECONDS
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS

    def __post_init__(self) -> None:
        if self.min_hold_seconds < MIN_CACHE_SECONDS:
            self.min_hold_seconds = MIN_CACHE_SECONDS
        if self.max_age_seconds < self.min_hold_seconds:
            self.max_age_seconds = self.min_hold_seconds
        self._items: dict[str, MarketSnapshot] = {}

    def get(self, token: str, now: datetime) -> MarketSnapshot | None:
        found = self._items.get(token)
        if found is None:
            return None
        if found.age_seconds(now) > self.max_age_seconds:
            return None
        return found

    def fresh_enough(self, token: str, now: datetime) -> bool:
        found = self.get(token, now)
        return found is not None and found.age_seconds(now) < self.min_hold_seconds

    def put(self, snapshot: MarketSnapshot) -> None:
        self._items[snapshot.token] = snapshot


def evm_canonical(address: str) -> str | None:
    """Lowercase 0x form. Not used for live calls; EVM chains are unsupported."""
    if not isinstance(address, str) or _EVM.fullmatch(address) is None:
        return None
    return "0x" + address[2:].lower()


def token_for_swap(swap: Swap) -> tuple[str | None, int | None, str]:
    """Return the coin leg. Buy uses the received token. Sell uses the sent token."""
    if swap.side == "sell":
        return swap.in_token, swap.token_network_id, "in"
    if swap.side == "buy":
        return swap.out_token, swap.token_network_id, "out"
    return None, None, "unknown"


def process_candidate(
    swap: Swap,
    *,
    cache: MarketCache | None = None,
    now: datetime | None = None,
    transport=None,
) -> MarketSnapshot:
    """One explicit lookup. Menus must not call this."""
    moment = now or datetime.now(timezone.utc)
    store = cache or MarketCache()
    token, network_id, _leg = token_for_swap(swap)
    if token is None or network_id is None:
        return _empty(token or "", network_id or 0, moment, "unknown-leg")
    if network_id not in DEX_CHAIN:
        return _empty(token, network_id, moment, "unsupported-chain")
    if not _SOLANA.fullmatch(token):
        return _empty(token, network_id, moment, "invalid-address")
    held = store.get(token, moment)
    if held is not None and store.fresh_enough(token, moment):
        return held
    try:
        body = _get_pairs(token, transport)
    except DexError:
        if held is not None:
            return held
        return _empty(token, network_id, moment, "fetch-failed")
    selected = select_pool(body, token)
    if selected is None:
        snapshot = _empty(token, network_id, moment, "unmatched")
    else:
        snapshot = MarketSnapshot(
            provider="dexscreener",
            pair_address=selected["pair_address"],
            chain="solana",
            token=token,
            network_id=network_id,
            fetched_at=moment,
            market_cap=selected["market_cap"],
            liquidity_usd=selected["liquidity_usd"],
            fdv=selected["fdv"],
            coverage="solana",
        )
    store.put(snapshot)
    return snapshot


def select_pool(payload: object, token: str) -> dict | None:
    """Highest valid liquidity.usd, then lowest pair address. Liquidity is not summed."""
    if not isinstance(payload, list):
        return None
    best: tuple[Decimal, str, dict] | None = None
    for pair in payload[:MAX_PAIRS]:
        parsed = _eligible(pair, token)
        if parsed is None:
            continue
        liquidity, pair_address, fields = parsed
        if best is None or liquidity > best[0] or (liquidity == best[0] and pair_address < best[1]):
            best = (liquidity, pair_address, fields)
    if best is None:
        return None
    return best[2]


def format_market_note(snapshot: MarketSnapshot, *, now: datetime, min_mcap: int | None, min_liq: int | None) -> str:
    age = snapshot.age_seconds(now)
    lines = [
        "Current DEX Screener data. Not the value at the swap source time.",
        "Fetched time is not a chain update time and is not a historical threshold pass.",
        f"provider {snapshot.provider}",
        f"chain {snapshot.chain or 'unsupported'}",
        f"token {snapshot.token}",
        f"pair {snapshot.pair_address or 'none'}",
        f"fetched_at {snapshot.fetched_at.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"age_seconds {age}",
        f"coverage {snapshot.coverage}",
    ]
    lines.append("market cap " + _show(snapshot.market_cap))
    lines.append("liquidity usd " + _show(snapshot.liquidity_usd))
    lines.append("fdv " + _show(snapshot.fdv) + " (not used for the market cap check)")
    if min_mcap is not None:
        lines.append(_threshold("market cap", snapshot.market_cap, Decimal(min_mcap)))
    if min_liq is not None:
        lines.append(_threshold("liquidity", snapshot.liquidity_usd, Decimal(min_liq)))
    return "\n".join(lines)


def build_url(token: str) -> str:
    if not isinstance(token, str) or _SOLANA.fullmatch(token) is None:
        raise DexError("token address is not a Solana address; stopped")
    if token != quote(token, safe=""):
        raise DexError("token address is not a Solana address; stopped")
    return f"{BASE_URL}/token-pairs/v1/solana/{token}"


def _get_pairs(token: str, transport) -> object:
    url = build_url(token)
    caller = transport or urllib_transport
    try:
        status, body = caller(url)
    except DexError:
        raise
    except Exception as exc:
        safe_text(exc)
        raise DexError("dex request failed; stopped") from None
    if not isinstance(status, int) or isinstance(status, bool) or status != 200:
        raise DexError(f"HTTP {status if isinstance(status, int) and not isinstance(status, bool) else 'unknown'}; stopped")
    if not isinstance(body, (bytes, bytearray)) or len(body) > MAX_BODY_BYTES:
        raise DexError("response unusable; stopped")
    try:
        return json.loads(bytes(body).decode("utf-8"), parse_float=Decimal)
    except (UnicodeError, json.JSONDecodeError) as exc:
        safe_text(exc)
        raise DexError("response was not JSON; stopped") from None


def urllib_transport(url: str) -> tuple[int, bytes]:
    if not url.startswith(f"{BASE_URL}/token-pairs/v1/solana/"):
        raise DexError("refusing non-dex URL; stopped")
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "copytrader-fomo-dex"},
        method="GET",
    )
    opener = guarded_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.status, response.read(MAX_BODY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        code = exc.code
        try:
            body = exc.read(4096)
        except Exception:
            body = b""
        safe_text(exc)
        return code, body
    except DexError:
        raise
    except Exception as exc:
        safe_text(exc)
        raise_clean(DexError("dex request failed; stopped"))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise_clean(DexError("HTTP redirect; stopped"))

    def http_error_302(self, req, fp, code, msg, headers):
        raise_clean(DexError("HTTP redirect; stopped"))

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _eligible(pair: object, token: str) -> tuple[Decimal, str, dict] | None:
    if not isinstance(pair, dict):
        return None
    if pair.get("chainId") != "solana":
        return None
    base = pair.get("baseToken")
    quote = pair.get("quoteToken")
    base_address = base.get("address") if isinstance(base, dict) else None
    quote_address = quote.get("address") if isinstance(quote, dict) else None
    if base_address != token:
        if quote_address == token:
            return None
        return None
    liquidity = pair.get("liquidity")
    usd = _non_negative(liquidity.get("usd") if isinstance(liquidity, dict) else None)
    pair_address = pair.get("pairAddress")
    if usd is None or not isinstance(pair_address, str) or not pair_address or any(ch in pair_address for ch in "\r\n"):
        return None
    return usd, pair_address, {
        "pair_address": pair_address,
        "liquidity_usd": usd,
        "market_cap": _non_negative(pair.get("marketCap")),
        "fdv": _non_negative(pair.get("fdv")),
    }


def _non_negative(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        number = Decimal(str(value))
    else:
        return None
    if not number.is_finite() or number < 0:
        return None
    return number


def _empty(token: str, network_id: int, moment: datetime, coverage: str) -> MarketSnapshot:
    return MarketSnapshot(
        provider="dexscreener",
        pair_address=None,
        chain="solana" if network_id == SOLANA_NETWORK_ID else None,
        token=token,
        network_id=network_id,
        fetched_at=moment,
        market_cap=None,
        liquidity_usd=None,
        fdv=None,
        coverage=coverage,
    )


def _show(value: Decimal | None) -> str:
    if value is None:
        return "unknown"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _threshold(name: str, value: Decimal | None, limit: Decimal) -> str:
    if value is None:
        return f"{name} unknown; cannot be passed"
    if value < limit:
        return f"{name} {_show(value)} below {_show(limit)}"
    return f"{name} {_show(value)} meets {_show(limit)}"
