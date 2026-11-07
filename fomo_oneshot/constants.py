"""Bounds and the link facts this package is allowed to use."""

from __future__ import annotations

from datetime import timedelta, timezone

# pumpfomo public reference (unofficial read-only data API, not fomo.family):
# https://pumpfomo.com/docs/fomo-user
# https://pumpfomo.com/docs/fomo-user-positions
# https://pumpfomo.com/docs/fomo-user-following
API_ORIGIN = "https://api.pumpfomo.com"
POSITIONS_PATH = "/v1/fomo/users/{handle}/positions"
FOLLOWING_PATH = "/v1/fomo/users/{handle}/following"

# Published desk coin links use this host, path, and referral.
# Profile links in the same snapshot already include source=share_link.
FOMO_ORIGIN = "https://fomo.family"
REFERRAL = "savipww"
SHARE_SOURCE = "share_link"
OPEN_FOMO_URL = "https://fomo.family/r/savipww"

# Coin URLs are built only for these network ids. Anything else uses OPEN_FOMO_URL.
CHAINS = {
    1399811149: "Solana",
    4663: "Robinhood",
    8453: "Base",
    56: "BNB",
}

# Owner chat for @wyatt_desk_bot. Also desk.owner_chat_id in the published snapshot.
OWNER_CHAT_ID = 8578901453
DEFAULT_HANDLE = "PressingProfits"

MAX_REQUESTS = 3
MAX_ROWS = 50
MAX_BODY_BYTES = 1_000_000
MAX_SEEN_BYTES = 1_000_000
HTTP_TIMEOUT_SECONDS = 20

# Atlantic Standard Time is a fixed UTC-4 offset. America/Halifax observes daylight time.
AST = timezone(timedelta(hours=-4), name="AST")
MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
