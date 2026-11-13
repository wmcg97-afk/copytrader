"""Local seen-id file. This is not the desk database."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .constants import MAX_SEEN_BYTES
from .swap import is_swap_id, normalize_handle

_REPO_DATA = Path(__file__).resolve().parents[1] / "d"


class SeenError(Exception):
    def __init__(self, message: str = "seen store unreadable; stopped"):
        super().__init__(message)


@dataclass
class HandleSeen:
    seeded: bool = False
    ids: list[str] = field(default_factory=list)

    def add(self, swap_id: str) -> None:
        if swap_id not in self.ids:
            self.ids.append(swap_id)


@dataclass
class SeenStore:
    handles: dict[str, HandleSeen] = field(default_factory=dict)

    def for_handle(self, handle: str) -> HandleSeen:
        key = handle.casefold()
        found = self.handles.get(key)
        if found is None:
            found = HandleSeen()
            self.handles[key] = found
        return found


def assert_safe_seen_path(path: Path) -> None:
    if path.name in {"state.json", "activity.json", "chart.json"}:
        raise SeenError("seen store cannot use a published desk filename")
    resolved = path.resolve()
    data_root = _REPO_DATA.resolve()
    if resolved == data_root or data_root in resolved.parents:
        raise SeenError("seen store cannot be inside published desk data")


def load_seen(path: Path) -> SeenStore:
    assert_safe_seen_path(path)
    if not path.exists():
        return SeenStore()
    size = path.stat().st_size
    if size > MAX_SEEN_BYTES:
        raise SeenError()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SeenError() from exc
    return _parse(payload)


def save_seen(path: Path, store: SeenStore) -> None:
    assert_safe_seen_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "version": 1,
        "handles": {
            key: {"seeded": value.seeded, "ids": list(value.ids)}
            for key, value in store.handles.items()
        },
    }
    encoded = json.dumps(body, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)


def _parse(payload: object) -> SeenStore:
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise SeenError()
    raw_handles = payload.get("handles")
    if not isinstance(raw_handles, dict):
        raise SeenError()
    store = SeenStore()
    for key, value in raw_handles.items():
        if not isinstance(key, str):
            raise SeenError()
        try:
            handle = normalize_handle(key)
        except ValueError as exc:
            raise SeenError() from exc
        if not isinstance(value, dict) or not isinstance(value.get("seeded"), bool):
            raise SeenError()
        raw_ids = value.get("ids")
        if not isinstance(raw_ids, list):
            raise SeenError()
        ids: list[str] = []
        for swap_id in raw_ids:
            if not is_swap_id(swap_id):
                raise SeenError()
            if swap_id not in ids:
                ids.append(swap_id)
        store.handles[handle.casefold()] = HandleSeen(seeded=value["seeded"], ids=ids)
    return store
