"""FOMO open links. Manual open only; this never calls a buy or sell route."""

from __future__ import annotations

import re
from urllib.parse import quote, urlencode

from .constants import CHAINS, FOMO_ORIGIN, OPEN_FOMO_URL, REFERRAL, SHARE_SOURCE
from .swap import Swap, normalize_handle

_SOL_ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


def fomo_url(swap: Swap) -> str:
    """Coin link for a supported chain, otherwise the published invite URL.

    The path and the address, chainId, and r parameters match coin links in the
    published desk snapshot. source=share_link is the share parameter already
    used on the profile URL in that snapshot.
    """
    token = swap.traded_token
    chain = swap.token_network_id
    if token and chain in CHAINS and _address_ok(token):
        query = urlencode(
            (
                ("address", token),
                ("chainId", str(chain)),
                ("r", REFERRAL),
                ("source", SHARE_SOURCE),
            )
        )
        return f"{FOMO_ORIGIN}/coin?{query}"
    return OPEN_FOMO_URL


def profile_url(handle: str) -> str:
    """Profile share link. Matches the published desk profile URL shape."""
    safe = quote(normalize_handle(handle), safe="._")
    query = urlencode((("source", SHARE_SOURCE), ("r", REFERRAL)))
    return f"{FOMO_ORIGIN}/profile/{safe}?{query}"


def _address_ok(token: str) -> bool:
    return _SOL_ADDRESS.fullmatch(token) is not None or _EVM_ADDRESS.fullmatch(token) is not None
