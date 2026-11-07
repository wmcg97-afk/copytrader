"""Map one positions-page swap. Missing and malformed fields stay null."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .constants import MAX_ROWS

_ID = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_HANDLE = re.compile(r"^@?[A-Za-z0-9_.]{1,32}$")


@dataclass(frozen=True)
class Swap:
    id: str | None
    side: str | None
    created_at: str | None
    provider: str | None
    network_id: int | None
    in_network_id: int | None
    out_network_id: int | None
    in_token: str | None
    out_token: str | None
    in_amount: Decimal | None
    out_amount: Decimal | None
    usd_in: Decimal | None
    usd_out: Decimal | None
    price: Decimal | None
    is_off_platform: bool | None
    is_crossmint: bool | None
    address: str | None
    recipient: str | None
    in_trade_id: str | None
    out_trade_id: str | None

    @property
    def traded_token(self) -> str | None:
        if self.side == "sell":
            return self.in_token
        if self.side == "buy":
            return self.out_token
        return None

    @property
    def token_network_id(self) -> int | None:
        if self.side == "sell":
            if self.in_network_id is not None:
                return self.in_network_id
            return self.network_id
        if self.side == "buy":
            if self.out_network_id is not None:
                return self.out_network_id
            return self.network_id
        return None


@dataclass(frozen=True)
class PositionsPage:
    swaps: tuple[Swap, ...]
    has_next_page: bool | None
    truncated: bool
    skipped_malformed: int
    note: str | None


def normalize_handle(raw: str) -> str:
    text = raw.strip()
    if not _HANDLE.fullmatch(text) or text in {".", ".."}:
        raise ValueError("handle is not a fomo.family handle")
    return text[1:] if text.startswith("@") else text


def is_swap_id(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def parse_positions(payload: object) -> PositionsPage:
    if not isinstance(payload, dict):
        return PositionsPage((), None, False, 0, "positions response was not an object; swaps not guessed")
    data = payload.get("data")
    if not isinstance(data, dict) or "swaps" not in data:
        return PositionsPage((), None, False, 0, "positions response had no data.swaps; swaps not guessed")
    rows = data.get("swaps")
    if not isinstance(rows, list):
        return PositionsPage((), None, False, 0, "data.swaps was not a list; swaps not guessed")
    flag = data.get("hasNextPage")
    has_next = flag if isinstance(flag, bool) else None
    truncated = len(rows) > MAX_ROWS
    skipped = 0
    swaps: list[Swap] = []
    for row in rows[:MAX_ROWS]:
        if not isinstance(row, dict):
            skipped += 1
            continue
        swaps.append(_swap(row))
    return PositionsPage(tuple(swaps), has_next, truncated, skipped, None)


def parse_following(payload: object) -> tuple[tuple[str, ...] | None, str | None]:
    """Return handles from data.users[].userHandle, or a note when that list is absent."""
    if not isinstance(payload, dict):
        return None, "following response was not an object; handles not guessed"
    data = payload.get("data")
    if not isinstance(data, dict) or "users" not in data:
        return None, "following response had no data.users; handles not guessed"
    users = data.get("users")
    if not isinstance(users, list):
        return None, "data.users was not a list; handles not guessed"
    handles: list[str] = []
    for user in users[:MAX_ROWS]:
        if not isinstance(user, dict):
            continue
        raw = user.get("userHandle")
        if not isinstance(raw, str) or not _HANDLE.fullmatch(raw.strip()):
            continue
        handle = raw.strip()
        if handle in {".", ".."}:
            continue
        handles.append(handle[1:] if handle.startswith("@") else handle)
    return tuple(handles), None


def _swap(row: dict) -> Swap:
    return Swap(
        id=_id(row.get("id")),
        side=_side(row.get("display")),
        created_at=_line(row.get("createdAt"), 40),
        provider=_line(row.get("provider"), 32),
        network_id=_int(row.get("networkId")),
        in_network_id=_int(row.get("inNetworkId")),
        out_network_id=_int(row.get("outNetworkId")),
        in_token=_line(row.get("inTokenAddress"), 128),
        out_token=_line(row.get("outTokenAddress"), 128),
        in_amount=_decimal(row.get("inHumanAmount")),
        out_amount=_decimal(row.get("outHumanAmount")),
        usd_in=_decimal(row.get("humanUsdAmountIn")),
        usd_out=_decimal(row.get("humanUsdAmountOut")),
        price=_decimal(row.get("displayPriceUsd")),
        is_off_platform=_bool(row.get("isOffPlatform")),
        is_crossmint=_bool(row.get("isCrossmint")),
        address=_line(row.get("address"), 128),
        recipient=_line(row.get("recipient"), 128),
        in_trade_id=_id(row.get("inTradeId")),
        out_trade_id=_id(row.get("outTradeId")),
    )


def _side(display: object) -> str | None:
    if not isinstance(display, dict):
        return None
    raw = display.get("side")
    if not isinstance(raw, str):
        return None
    side = raw.strip().lower()
    if side in {"buy", "sell"}:
        return side
    return None


def _line(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    if any(ch in value for ch in "\r\n\x00"):
        return None
    text = value.strip()
    if not text or len(text) > limit:
        return None
    return text


def _id(value: object) -> str | None:
    text = _line(value, 128)
    if text is None or not _ID.fullmatch(text):
        return None
    return text


def _int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _decimal(value: object) -> Decimal | None:
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
    if not number.is_finite():
        return None
    return number
