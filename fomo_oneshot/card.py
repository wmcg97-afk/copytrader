"""Plain-text historical card. HTML escaping happens at the Telegram boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .constants import AST, CHAINS, MONTHS
from .links import fomo_url
from .swap import Swap

BUTTON_TEXT = "Open FOMO"


@dataclass(frozen=True)
class Card:
    text: str
    button_text: str
    button_url: str


def build_card(*, handle: str, swap: Swap, fixture: bool, replay: bool) -> Card:
    lines = ["TEST / HISTORICAL"]
    if fixture:
        lines.append("FIXTURE — not a live capture and not data verification.")
    if replay:
        lines.append("Historical replay of one fetched swap.")
    else:
        lines.append("Historical record from one fetched page.")
    lines.append("Not a live buy or sell signal. Not a recommendation.")
    lines.append("")
    lines.append(f"@{handle}")
    lines.append(swap.side or "side unknown")
    if swap.side == "sell":
        lines.append(f"sold {_fmt(swap.in_amount)}")
        lines.append(f"received {_fmt(swap.out_amount)}")
    elif swap.side == "buy":
        lines.append(f"spent {_fmt(swap.in_amount)}")
        lines.append(f"received {_fmt(swap.out_amount)}")
    else:
        lines.append(f"in amount {_fmt(swap.in_amount)}")
        lines.append(f"out amount {_fmt(swap.out_amount)}")
    lines.append(f"token {swap.traded_token}" if swap.traded_token else "token unknown")
    lines.append(_usd(swap))
    lines.append(f"price {_fmt(swap.price)}" if swap.price is not None else "price unknown")
    lines.append(_chain(swap))
    if swap.cross_chain:
        lines.append(f"cross-chain in {swap.in_network_id} out {swap.out_network_id}")
    lines.append(f"provider {swap.provider}" if swap.provider else "provider unknown")
    if swap.is_off_platform is True:
        lines.append("off-platform")
    if swap.created_at:
        lines.append(f"source time {swap.created_at}")
        lines.append(_ast(swap.created_at) or "local time unknown")
    else:
        lines.append("source time unknown")
    return Card(text="\n".join(lines), button_text=BUTTON_TEXT, button_url=fomo_url(swap))


def _fmt(value: Decimal | None) -> str:
    if value is None:
        return "unknown"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _usd(swap: Swap) -> str:
    if swap.usd_in is not None and swap.usd_out is not None:
        if swap.usd_in == swap.usd_out:
            return f"USD {_fmt(swap.usd_in)}"
        return f"USD in {_fmt(swap.usd_in)} / USD out {_fmt(swap.usd_out)}"
    if swap.usd_in is not None:
        return f"USD {_fmt(swap.usd_in)}"
    if swap.usd_out is not None:
        return f"USD {_fmt(swap.usd_out)}"
    return "USD unknown"


def _chain(swap: Swap) -> str:
    chain_id = swap.token_network_id
    if chain_id is None:
        if swap.in_network_id is not None or swap.out_network_id is not None or swap.network_id is None:
            return "chain unknown"
        return f"network id {swap.network_id}"
    name = CHAINS.get(chain_id)
    if name is None:
        return f"chain {chain_id}"
    return f"{name} {chain_id}"


def _ast(value: str) -> str | None:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    local = parsed.astimezone(AST)
    month = MONTHS[local.month - 1]
    return f"{month} {local.day} {local.hour:02d}:{local.minute:02d}:{local.second:02d} AST"
