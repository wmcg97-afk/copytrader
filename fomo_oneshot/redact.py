"""Last-line scrub for tokens that must never reach a report."""

from __future__ import annotations

import re

_BEARER = re.compile(r"(?i)(bearer\s+)\S+")
_PF_LIVE = re.compile(r"pf_live_\S+", re.IGNORECASE)
_TELEGRAM_URL = re.compile(r"https://api\.telegram\.org/bot\S+", re.IGNORECASE)
_BOT_TOKEN = re.compile(r"\bbot\d+:[A-Za-z0-9_-]+")


def redact(text: str) -> str:
    cleaned = _TELEGRAM_URL.sub("https://api.telegram.org/bot[redacted]", text)
    cleaned = _BEARER.sub(r"\1[redacted]", cleaned)
    cleaned = _PF_LIVE.sub("[redacted]", cleaned)
    cleaned = _BOT_TOKEN.sub("bot[redacted]", cleaned)
    return cleaned
