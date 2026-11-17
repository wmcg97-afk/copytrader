"""Dry-run CLI. --send is the only path that can message Telegram."""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

from .constants import DEFAULT_HANDLE, MAX_BODY_BYTES, MAX_REQUESTS
from .engine import RunConfig, execute, render_report
from .seen import SeenError, assert_safe_seen_path
from .swap import normalize_handle


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        handle = normalize_handle(args.handle)
        assert_safe_seen_path(args.seen)
    except (ValueError, SeenError) as exc:
        sys.stdout.write(f"stopped: {exc}\nsends: 0\n")
        return 2

    if args.max_requests < 0:
        sys.stdout.write("stopped: request cap is not usable\nsends: 0\n")
        return 2

    telegram = os.environ.get("TELEGRAM_BOT_TOKEN")
    if args.send and not _usable_secret(telegram):
        sys.stdout.write("stopped: TELEGRAM_BOT_TOKEN is not set\nsends: 0\n")
        return 2

    api_key = None
    payload = None
    transport = None
    if args.fixture:
        try:
            payload = _read_fixture(args.fixture)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            sys.stdout.write(f"stopped: fixture unreadable\nsends: 0\n")
            return 2
    else:
        api_key = os.environ.get("PUMPFOMO_API_KEY")
        if not _usable_secret(api_key):
            sys.stdout.write("stopped: PUMPFOMO_API_KEY is not set\nsends: 0\n")
            return 2
        from .client import urllib_transport

        transport = urllib_transport

    send_transport = None
    if args.send:
        from .telegram import urllib_send

        send_transport = urllib_send

    result = execute(
        RunConfig(
            handle=handle,
            replay=args.replay,
            send=args.send,
            following=args.following,
            seen_path=args.seen,
            fixture=args.fixture is not None,
            max_requests=min(args.max_requests, MAX_REQUESTS),
            api_key=api_key,
            telegram_token=telegram if args.send else None,
            positions_payload=payload,
        ),
        transport=transport,
        send_transport=send_transport,
    )
    sys.stdout.write(render_report(result))
    if result.stopped is None:
        return 0
    return 2 if result.config_error else 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fomo_oneshot",
        description=(
            "One-shot historical FOMO swap card. Dry-run by default. "
            "Does not trade, poll, or message Telegram unless --send is set."
        ),
    )
    parser.add_argument("--handle", default=DEFAULT_HANDLE, help=f"fomo.family handle (default {DEFAULT_HANDLE})")
    parser.add_argument(
        "--following",
        action="store_true",
        help="Also read who this handle follows. One extra request. Does not fetch each follow.",
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Render the newest swap on the page as a labeled historical test.",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send at most one card to the owner chat. Omit this for a dry-run.",
    )
    parser.add_argument("--fixture", type=Path, help="Offline positions JSON. No provider HTTP.")
    parser.add_argument("--seen", type=Path, default=Path(".fomo_oneshot/seen.json"))
    parser.add_argument("--max-requests", type=int, default=MAX_REQUESTS)
    return parser


def _usable_secret(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or any(ch in text for ch in "\r\n \t"):
        return False
    if text.lower().startswith("bearer "):
        return False
    return True


def _read_fixture(path: Path) -> object:
    if path.stat().st_size > MAX_BODY_BYTES:
        raise ValueError("fixture too large")
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
