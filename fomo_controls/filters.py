"""Filter checks. Missing cap, liquidity, and holders cannot pass an enabled threshold."""

from __future__ import annotations

from decimal import Decimal

from fomo_oneshot.swap import Swap

from .store import Settings


def filter_reasons(swap: Swap, settings: Settings) -> list[str]:
    reasons: list[str] = []
    amount = swap.usd_in if swap.usd_in is not None else swap.usd_out
    if amount is None:
        reasons.append("trade amount unknown")
    elif amount < Decimal(settings.min_trade_usd):
        reasons.append("below min trade")
    if swap.side == "sell" and not settings.show_sells:
        reasons.append("sells hidden")
    elif swap.side not in {"buy", "sell"}:
        reasons.append("side unknown")
    chain = swap.token_network_id
    if chain is None or chain not in settings.networks:
        reasons.append("network unknown")
    elif not settings.networks[chain]:
        reasons.append("network off")
    if settings.min_mcap_usd is not None:
        reasons.append("mcap unknown")
    if settings.min_liq_usd is not None:
        reasons.append("liquidity unknown")
    if settings.min_holders is not None:
        reasons.append("holders unknown")
    return reasons


def allowed(swap: Swap, settings: Settings) -> bool:
    return not filter_reasons(swap, settings)
