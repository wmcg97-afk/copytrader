"""Offline proof that /fomo joins the existing desk consumer without taking its commands."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from fomo_controls.desk_hook import DeskFomoHook, classify_callback, classify_text
from fomo_controls.install_desk import PATCHED, main as install_main
from fomo_oneshot.constants import OWNER_CHAT_ID

ARCHIVE = Path("/home/ubuntu/.cursor/projects/agent-repos-copytrader/uploads/runtime-source-sanitized.tar_b0f4.gz")
ARCHIVE_SHA = "d0708266321b24ae81c42e890fb2687e95c24c7164e9508a00f44471849038fa"
REPO = Path(__file__).resolve().parents[2]
MINT = "1" * 32


class RouteTests(unittest.TestCase):
    def test_desk_commands_win_and_fomo_waits_for_plain_text(self):
        for text in (
            "/start",
            "/help",
            "/status",
            "invite",
            "paper",
            "live",
            "LIVE",
            "pause Scanner",
            "resume risk",
            "stack 1240",
            "set stop to -8%",
            "buy pip",
            "sell pip",
            "why pip",
            "/start@wyatt_desk_bot",
        ):
            raw = _normalize(text)
            self.assertEqual(classify_text(raw, awaiting="add"), "desk", text)
        self.assertEqual(classify_text("fomo", awaiting=None), "fomo")
        self.assertEqual(classify_text("fomo add Alpha_1", awaiting=None), "fomo")
        self.assertEqual(classify_text("hello", awaiting=None), "desk_help")
        self.assertEqual(classify_text("Alpha_1", awaiting="add"), "fomo")
        self.assertEqual(classify_callback("bought:" + MINT), "desk_trade")
        self.assertEqual(classify_callback("sold:" + MINT), "desk_trade")
        self.assertEqual(classify_callback("m:f"), "fomo")
        self.assertEqual(classify_callback("a:d:<script>"), "desk_other")


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "controls.json"
        self.http = FakeHttp()
        self.hook = DeskFomoHook(self.path, self.http, lambda: "TESTTOKEN", lambda: OWNER_CHAT_ID)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fomo_menu_edit_resume_and_non_owner_do_not_call_provider(self):
        self.assertTrue(asyncio.run(self.hook.maybe_text("fomo", OWNER_CHAT_ID, OWNER_CHAT_ID)))
        self.assertEqual(self.http.methods(), ["sendMessage"])
        self.assertEqual(self.hook.store.menu_message_id, 55)
        self.assertIn("Monitoring is inactive", self.http.calls[0]["json"]["text"])
        self.assertTrue(asyncio.run(self.hook.maybe_callback(
            _cq("m:f", 55), "m:f", OWNER_CHAT_ID, OWNER_CHAT_ID,
        )))
        self.assertEqual(self.http.methods(), ["sendMessage", "answerCallbackQuery", "editMessageText"])
        self.assertEqual(self.http.calls[-1]["json"]["message_id"], 55)
        self.assertIn("cannot be passed", self.http.calls[-1]["json"]["text"])
        self.assertTrue(all(call["follow_redirects"] is False for call in self.http.calls))
        self.assertFalse(self.hook.store.paused is False)
        asyncio.run(self.hook.maybe_callback(_cq("c:resume", 55), "c:resume", OWNER_CHAT_ID, OWNER_CHAT_ID))
        self.assertFalse(self.hook.store.paused)
        self.assertIn("does not start polling", self.http.calls[-1]["json"]["text"])
        self.assertIn("No monitoring budget is approved", self.http.calls[-1]["json"]["text"])
        before = self.path.read_text(encoding="utf-8")
        calls = len(self.http.calls)
        self.assertTrue(asyncio.run(self.hook.maybe_text("fomo", OWNER_CHAT_ID, 111)))
        self.assertTrue(asyncio.run(self.hook.maybe_callback(_cq("a:Y", 55), "a:Y", 5, OWNER_CHAT_ID)))
        self.assertEqual(len(self.http.calls), calls)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        self.assertNotIn("TESTTOKEN", before)
        self.assertFalse(any("pumpfomo" in call["url"] or "getUpdates" in call["url"] for call in self.http.calls))

    def test_unconfirmed_send_is_not_repeated(self):
        self.http.fail_send = True
        asyncio.run(self.hook.maybe_text("fomo", OWNER_CHAT_ID, OWNER_CHAT_ID))
        self.assertEqual(self.http.methods(), ["sendMessage"])
        self.assertIsNone(self.hook.store.menu_message_id)

    def test_add_text_does_not_fetch(self):
        asyncio.run(self.hook.maybe_text("fomo", OWNER_CHAT_ID, OWNER_CHAT_ID))
        asyncio.run(self.hook.maybe_callback(_cq("a:n", 55), "a:n", OWNER_CHAT_ID, OWNER_CHAT_ID))
        asyncio.run(self.hook.maybe_text("NewTrader1", OWNER_CHAT_ID, OWNER_CHAT_ID))
        self.assertIsNotNone(self.hook.store.find("NewTrader1"))
        self.assertFalse(self.hook.store.find("NewTrader1").seeded)
        self.assertNotIn("getUpdates", " ".join(self.http.methods()))


class DeskTelegramTests(unittest.TestCase):
    def setUp(self):
        if not ARCHIVE.is_file():
            self.skipTest("sanitized desk source archive is not in this environment")
        digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
        if digest != ARCHIVE_SHA:
            self.skipTest("desk source archive hash mismatch")
        self.tmp = tempfile.TemporaryDirectory()
        self.desk = Path(self.tmp.name) / "desk"
        self.desk.mkdir()
        with tarfile.open(ARCHIVE) as tar:
            member = tar.getmember("desk/telegram.py")
            extracted = tar.extractfile(member)
            original = extracted.read()
        (self.desk / "telegram.py").write_bytes(original)
        _write_stubs(self.desk)
        code = install_main(["--desk", str(self.desk), "--apply"])
        self.assertEqual(code, 0)
        self.assertEqual(hashlib.sha256((self.desk / "telegram.py").read_bytes()).hexdigest(), PATCHED)
        self.http = FakeHttp()
        self.settings = FakeSettings()
        self.db = FakeDB()
        self.bus = FakeBus()
        self.runtime = FakeRuntime()
        sys.path.insert(0, str(REPO))
        sys.path.insert(0, str(self.desk))
        self.mod = _load_telegram(self.desk / "telegram.py")
        self.bot = self.mod.Telegram(self.db, self.bus, self.settings, self.http, desk=self.runtime)

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()
        for entry in (str(self.desk), str(REPO)):
            while entry in sys.path:
                sys.path.remove(entry)
        sys.modules.pop("config", None)
        sys.modules.pop("links", None)

    def test_existing_commands_and_one_fomo_consumer(self):
        text = (self.desk / "telegram.py").read_text(encoding="utf-8")
        self.assertEqual(text.count("getUpdates"), 1)
        self.assertEqual(text.count("while True"), 1)
        self.assertEqual(text.count("async def poll"), 1)
        asyncio.run(self.bot.on_text("/start", OWNER_CHAT_ID, from_id=OWNER_CHAT_ID))
        self.assertIn("pause Scanner", self.http.calls[-1]["json"]["text"])
        asyncio.run(self.bot.on_text("status", OWNER_CHAT_ID, from_id=OWNER_CHAT_ID))
        self.assertIn("201.25", self.http.calls[-1]["json"]["text"])
        self.assertIn("PAPER", self.http.calls[-1]["json"]["text"])
        asyncio.run(self.bot.on_text("pause Scanner", OWNER_CHAT_ID, from_id=OWNER_CHAT_ID))
        self.assertIn("scanner", self.bus.paused)
        asyncio.run(self.bot.on_text("set stop to -8%", OWNER_CHAT_ID, from_id=OWNER_CHAT_ID))
        self.assertIn("risk.stop_pct", self.settings.changed)
        self.assertEqual(self.settings.values["scanner.min_liquidity_usd"], 40000.0)
        asyncio.run(self.bot.on_text("buy " + MINT, OWNER_CHAT_ID, from_id=OWNER_CHAT_ID))
        self.assertEqual(self.runtime.audited, [MINT])
        before = len(self.http.calls)
        asyncio.run(self.bot._on_callback({
            "id": "cq-buy",
            "data": "bought:" + MINT,
            "from": {"id": OWNER_CHAT_ID},
            "message": {"message_id": 3, "chat": {"id": OWNER_CHAT_ID}},
        }))
        self.assertEqual(self.runtime.bought_mints, [MINT])
        self.assertIn("Marked bought.", self.http.calls[-1]["json"]["text"])
        self.assertGreater(len(self.http.calls), before)
        calls_before_fomo = len(self.http.calls)
        asyncio.run(self.bot.on_text("/fomo", OWNER_CHAT_ID, from_id=OWNER_CHAT_ID))
        self.assertEqual(self.http.methods()[calls_before_fomo:], ["sendMessage"])
        self.assertIn("Monitoring is inactive", self.http.calls[-1]["json"]["text"])
        menu_id = self.bot._fomo_hook().store.menu_message_id
        self.assertEqual(menu_id, 55)
        asyncio.run(self.bot._on_callback({
            "id": "cq-f",
            "data": "m:a",
            "from": {"id": OWNER_CHAT_ID},
            "message": {"message_id": menu_id, "chat": {"id": OWNER_CHAT_ID}},
        }))
        self.assertEqual(self.http.calls[-1]["method_name"], "editMessageText")
        self.assertEqual(self.http.calls[-1]["json"]["message_id"], menu_id)
        self.assertIn("verified-follows-2026-11-07", self.http.calls[-1]["json"]["text"])
        asyncio.run(self.bot._on_callback({
            "id": "cq-add",
            "data": "a:n",
            "from": {"id": OWNER_CHAT_ID},
            "message": {"message_id": menu_id, "chat": {"id": OWNER_CHAT_ID}},
        }))
        asyncio.run(self.bot.on_text("NewTrader1", OWNER_CHAT_ID, from_id=OWNER_CHAT_ID))
        self.assertIsNotNone(self.bot._fomo_hook().store.find("NewTrader1"))
        asyncio.run(self.bot.on_text("status", OWNER_CHAT_ID, from_id=OWNER_CHAT_ID))
        self.assertIn("201.25", self.http.calls[-1]["json"]["text"])
        calls = len(self.http.calls)
        asyncio.run(self.bot.on_text("/fomo", OWNER_CHAT_ID, from_id=111))
        asyncio.run(self.bot._on_callback({
            "id": "cq-no",
            "data": "a:Y",
            "from": {"id": 222},
            "message": {"message_id": menu_id, "chat": {"id": OWNER_CHAT_ID}},
        }))
        self.assertEqual(len(self.http.calls), calls)
        self.assertIsNotNone(self.bot._fomo_hook().store.find("PressingProfits"))
        asyncio.run(self.bot._on_callback({
            "id": "cq-go",
            "data": "c:resume",
            "from": {"id": OWNER_CHAT_ID},
            "message": {"message_id": menu_id, "chat": {"id": OWNER_CHAT_ID}},
        }))
        self.assertIn("does not start polling", self.http.calls[-1]["json"]["text"])
        self.assertFalse(any("pumpfomo" in call["url"] or call["url"].endswith("/getUpdates") for call in self.http.calls))
        self.assertNotIn("TESTTOKEN", self.http.calls[-1]["json"]["text"])
        self.assertEqual(self.db.balance, 201.25)

    def test_installer_preserves_config_and_does_not_restart(self):
        settings = self.desk / "settings.json"
        secret = self.desk / "secrets" / "TG_TOKEN"
        database = self.desk / "data" / "desk.db"
        web = self.desk / "web" / "index.html"
        secret.parent.mkdir()
        database.parent.mkdir()
        web.parent.mkdir()
        settings.write_text('{"owner_chat_id": 8578901453}\n', encoding="utf-8")
        secret.write_text("do-not-copy\n", encoding="utf-8")
        database.write_bytes(b"db-bytes")
        web.write_text("desk page\n", encoding="utf-8")
        before = {path: path.read_bytes() for path in (settings, secret, database, web)}
        telegram_before = (self.desk / "telegram.py").read_bytes()
        self.assertEqual(install_main(["--desk", str(self.desk)]), 0)
        self.assertEqual((self.desk / "telegram.py").read_bytes(), telegram_before)
        self.assertEqual(install_main(["--desk", str(self.desk), "--apply"]), 0)
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertTrue((self.desk / "fomo_controls" / "desk_hook.py").is_file())
        self.assertFalse((self.desk / "telegram.py").read_text(encoding="utf-8").count("while True") != 1)


def _normalize(text: str) -> str:
    raw = text.strip()
    if raw.startswith("/"):
        raw = raw[1:]
        raw = raw.split("@", 1)[0]
    return raw


def _cq(data: str, message_id: int) -> dict:
    return {
        "id": "cb",
        "data": data,
        "from": {"id": OWNER_CHAT_ID},
        "message": {"message_id": message_id, "chat": {"id": OWNER_CHAT_ID}},
    }


def _write_stubs(desk: Path) -> None:
    (desk / "config.py").write_text(
        "def format_change(key, old, new):\n"
        "    return f'{key} {old} -> {new}'\n",
        encoding="utf-8",
    )
    (desk / "links.py").write_text(
        "SIGNUP_URL = 'https://fomo.family/r/savipww'\n"
        "def coin_url(address, chain='solana'):\n"
        "    return f'https://fomo.family/coin?address={address}&chainId=1399811149&r=savipww'\n",
        encoding="utf-8",
    )


def _load_telegram(path: Path):
    spec = importlib.util.spec_from_file_location("desk_telegram_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeHttp:
    def __init__(self):
        self.calls = []
        self.fail_send = False

    def methods(self):
        return [call["method_name"] for call in self.calls]

    async def post(self, url, json=None, timeout=None, follow_redirects=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append({
            "url": url,
            "json": json,
            "follow_redirects": follow_redirects,
            "method_name": method,
        })
        if method == "sendMessage" and self.fail_send:
            return FakeResp(200, {"ok": False})
        if method == "sendMessage":
            return FakeResp(200, {"ok": True, "result": {"message_id": 55}})
        if method == "editMessageText":
            return FakeResp(200, {"ok": True, "result": {"message_id": json["message_id"]}})
        if method == "answerCallbackQuery":
            return FakeResp(200, {"ok": True, "result": True})
        raise AssertionError(method)

    async def get(self, *args, **kwargs):
        raise AssertionError("get")


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class FakeSettings:
    def __init__(self):
        self.values = {
            "desk.owner_chat_id": OWNER_CHAT_ID,
            "desk.mode": "PAPER",
            "desk.paper_start_stack": 201.25,
            "scanner.min_liquidity_usd": 40000.0,
        }
        self.secrets = {"TG_TOKEN": "TESTTOKEN"}
        self.changed = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, name, value, source="app"):
        key = "risk.stop_pct" if "stop" in str(name) else name
        old = self.values.get(key)
        self.values[key] = value
        self.changed.append(key)
        return key, old, value, True

    def ticket_check(self):
        return {}


class FakeDB:
    def __init__(self):
        self.balance = 201.25

    def latest_balance(self):
        return self.balance

    def open_positions(self):
        return []

    def find_coins(self, query):
        return []

    def latest_signal(self, mint):
        return None

    def open_for_mint(self, mint):
        return None

    def scans_for(self, mint, limit):
        return []

    def latest_audit(self, mint):
        return None

    def recent_verdicts(self, limit):
        return []

    def recent_positions(self, limit):
        return []

    def get_coin(self, mint):
        return None

    def upsert_coin(self, **kwargs):
        return None


class FakeBus:
    def __init__(self):
        self.paused = set()

    def pause(self, agent):
        self.paused.add(agent.lower())

    def resume(self, agent):
        self.paused.discard(agent.lower())


class FakeRuntime:
    def __init__(self):
        self.bought_mints = []
        self.sold_mints = []
        self.audited = []

    async def bought(self, mint):
        self.bought_mints.append(mint)

    async def sold(self, mint):
        self.sold_mints.append(mint)

    async def audit_now(self, mint):
        self.audited.append(mint)
        return None

    async def resend_buy(self, mint):
        return None

    def apply_stop_to_open(self, new_stop):
        self.stop = new_stop


if __name__ == "__main__":
    unittest.main()
