"""One invocation: at most one page of swaps, at most one card."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .card import build_card
from .client import Budget, CapError, ProviderError, following_url, get_json, positions_url
from .constants import MAX_REQUESTS
from .redact import redact
from .seen import SeenError, load_seen, save_seen
from .swap import Swap, normalize_handle, parse_following, parse_positions
from .telegram import NotifyError, send_one


@dataclass
class RunConfig:
    handle: str
    replay: bool
    send: bool
    following: bool
    seen_path: Path
    fixture: bool
    max_requests: int = MAX_REQUESTS
    api_key: str | None = None
    telegram_token: str | None = None
    positions_payload: object | None = None
    following_payload: object | None = None


@dataclass
class RunResult:
    handle: str
    replay: bool
    fixture: bool
    send_requested: bool
    requests: list[str]
    request_cap: int
    sends: int
    first_run: bool
    seen_count: int
    candidate_id: str | None
    deferred_unseen: int
    has_next_page: bool | None
    truncated: bool
    skipped_malformed: int
    following_handles: tuple[str, ...] | None
    following_note: str | None
    stopped: str | None
    config_error: bool
    card_text: str | None
    button_url: str | None
    seen_path: str
    page_note: str | None


def execute(config: RunConfig, *, transport=None, send_transport=None) -> RunResult:
    budget = Budget(config.max_requests)
    result = RunResult(
        handle=config.handle,
        replay=config.replay,
        fixture=config.fixture,
        send_requested=config.send,
        requests=[],
        request_cap=budget.limit,
        sends=0,
        first_run=False,
        seen_count=0,
        candidate_id=None,
        deferred_unseen=0,
        has_next_page=None,
        truncated=False,
        skipped_malformed=0,
        following_handles=None,
        following_note=None,
        stopped=None,
        config_error=False,
        card_text=None,
        button_url=None,
        seen_path=str(config.seen_path),
        page_note=None,
    )
    try:
        handle = normalize_handle(config.handle)
    except ValueError as exc:
        return _stop(result, str(exc), config_error=True)
    result.handle = handle
    try:
        store = load_seen(config.seen_path)
    except SeenError as exc:
        return _stop(result, str(exc), config_error=True)

    record = store.for_handle(handle)
    result.first_run = not record.seeded
    try:
        positions = _positions(config, handle, budget, transport, result)
    except (ProviderError, CapError, ValueError) as exc:
        return _stop(result, str(exc), config_error=isinstance(exc, ValueError))
    if result.page_note:
        return _stop(result, result.page_note, config_error=False)
    try:
        if config.following:
            _following(config, handle, budget, transport, result)
    except (ProviderError, CapError, ValueError) as exc:
        return _stop(result, str(exc), config_error=isinstance(exc, ValueError))

    swaps = positions.swaps
    result.has_next_page = positions.has_next_page
    result.truncated = positions.truncated
    result.skipped_malformed = positions.skipped_malformed

    if result.first_run:
        for swap in swaps:
            if swap.id:
                record.add(swap.id)
        record.seeded = True
        try:
            save_seen(config.seen_path, store)
        except SeenError as exc:
            return _stop(result, str(exc), config_error=True)

    candidate, deferred = _candidate(swaps, record.ids, replay=config.replay, first_run=result.first_run)
    result.deferred_unseen = deferred
    result.candidate_id = candidate.id if candidate and candidate.id else None
    if candidate is not None:
        card = build_card(handle=handle, swap=candidate, fixture=config.fixture, replay=config.replay)
        result.card_text = card.text
        result.button_url = card.button_url
        if config.send:
            try:
                send_one(token=config.telegram_token or "", card=card, transport=_require_send(send_transport))
            except NotifyError as exc:
                result.seen_count = len(record.ids)
                return _stop(result, str(exc), config_error=_is_config_notify(str(exc)))
            result.sends = 1
            if not config.replay and candidate.id:
                record.add(candidate.id)
                try:
                    save_seen(config.seen_path, store)
                except SeenError as exc:
                    return _stop(result, str(exc), config_error=True)
    result.seen_count = len(record.ids)
    return result


def render_report(result: RunResult) -> str:
    mode = "send" if result.send_requested else "dry-run"
    rows = [
        f"mode: {mode}",
        f"replay: {'yes' if result.replay else 'no'}",
        f"fixture: {'yes' if result.fixture else 'no'}",
        f"handle: {result.handle}",
        f"requests: {len(result.requests)}",
        f"request_cap: {result.request_cap}",
        f"sends: {result.sends}",
        f"first_run: {'yes' if result.first_run else 'no'}",
        f"seen_ids: {result.seen_count}",
        f"candidate: {result.candidate_id or 'none'}",
        f"deferred_unseen: {result.deferred_unseen}",
        f"has_next_page: {_yes_no(result.has_next_page)}",
        f"truncated: {'yes' if result.truncated else 'no'}",
        f"skipped_malformed: {result.skipped_malformed}",
        f"stopped: {result.stopped or 'no'}",
        f"seen: {result.seen_path}",
    ]
    if result.following_handles is not None or result.following_note:
        if result.following_handles is None:
            rows.append("following: unknown")
        elif result.following_handles:
            rows.append("following: " + ", ".join(result.following_handles))
        else:
            rows.append("following: none")
        if result.following_note:
            rows.append(f"following_note: {result.following_note}")
    if result.page_note and result.stopped != result.page_note:
        rows.append(f"page_note: {result.page_note}")
    for path in result.requests:
        rows.append(f"GET {path}")
    if result.card_text:
        rows.append(f"button: Open FOMO {result.button_url}")
        rows.append("card:")
        rows.append(result.card_text)
    return redact("\n".join(rows) + "\n")


def _positions(config, handle, budget, transport, result):
    if config.positions_payload is not None:
        page = parse_positions(config.positions_payload)
        result.page_note = page.note
        return page
    if not budget.allow():
        raise ProviderError("request cap reached; no provider call; stopped")
    url = positions_url(handle)
    payload = get_json(url, token=config.api_key or "", transport=_require_transport(transport), budget=budget)
    result.requests.append(_path(url))
    page = parse_positions(payload)
    result.page_note = page.note
    return page


def _following(config, handle, budget, transport, result) -> None:
    if config.positions_payload is not None and config.following_payload is None:
        result.following_note = "following skipped; positions came from a fixture"
        return
    if config.following_payload is not None:
        handles, note = parse_following(config.following_payload)
        result.following_handles = handles
        result.following_note = note
        return
    if not budget.allow():
        result.following_handles = None
        result.following_note = "following skipped; request cap reached"
        return
    url = following_url(handle)
    payload = get_json(url, token=config.api_key or "", transport=_require_transport(transport), budget=budget)
    result.requests.append(_path(url))
    handles, note = parse_following(payload)
    result.following_handles = handles
    result.following_note = note


def _candidate(swaps: tuple[Swap, ...], seen_ids: list[str], *, replay: bool, first_run: bool):
    if replay:
        chosen = next((swap for swap in swaps if swap.id), None)
        return chosen, 0
    if first_run:
        return None, 0
    unseen = [swap for swap in swaps if swap.id and swap.id not in seen_ids]
    if not unseen:
        return None, 0
    return unseen[0], len(unseen) - 1


def _require_transport(transport):
    if transport is None:
        raise ProviderError("no HTTP transport; stopped")
    return transport


def _require_send(transport):
    if transport is None:
        raise NotifyError("no Telegram transport; not sent")
    return transport


def _path(url: str) -> str:
    marker = "https://api.pumpfomo.com"
    if url.startswith(marker):
        return url[len(marker):]
    return url


def _stop(result: RunResult, message: str, *, config_error: bool) -> RunResult:
    result.stopped = redact(message)
    result.config_error = config_error
    result.sends = 0
    return result


def _is_config_notify(message: str) -> bool:
    return "TELEGRAM_BOT_TOKEN" in message or "not the owner chat" in message or "no Telegram transport" in message


def _yes_no(value: bool | None) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"
