"""Offline account controls, filters, and owner checks."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fomo_controls.apply import apply
from fomo_controls.demo import transcript
from fomo_controls.filters import allowed, filter_reasons
from fomo_controls.store import (
    VERIFIED_FOLLOWS,
    VERIFIED_SOURCE,
    ControlsError,
    load_store,
    new_store,
    save_store,
    seed_snapshot,
    to_dict,
)
from fomo_oneshot.constants import OPEN_FOMO_URL
from fomo_oneshot.links import profile_url
from fomo_oneshot.swap import Swap

OWNER = 8578901453
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
TOKEN = "BtSvtGREKtTWuc5YMQE1SVHJsGCb5YCyFS8G73sypump"


def message(text, *, chat_id=OWNER, from_id=OWNER):
    return {"message": {"message_id": 9, "text": text, "chat": {"id": chat_id}, "from": {"id": from_id}}}


def callback(data, *, chat_id=OWNER, from_id=OWNER, message_id=10):
    return {
        "callback_query": {
            "id": "cb",
            "data": data,
            "from": {"id": from_id},
            "message": {"message_id": message_id, "chat": {"id": chat_id}},
        }
    }


def swap(**kwargs) -> Swap:
    base = dict(
        id="swap-1",
        side="buy",
        created_at=None,
        provider=None,
        network_id=1399811149,
        in_network_id=1399811149,
        out_network_id=1399811149,
        in_token="0x0000000000000000000000000000000000000001",
        out_token=TOKEN,
        in_amount=None,
        out_amount=None,
        usd_in=None,
        usd_out=None,
        price=None,
        is_off_platform=None,
        is_crossmint=None,
        address=None,
        recipient=None,
        in_trade_id=None,
        out_trade_id=None,
    )
    base.update(kwargs)
    return Swap(**base)


def positions(swap_id, *, side="buy", chain=1399811149, usd=80, created="2026-11-07T11:59:00Z", token=TOKEN):
    incoming = token if side == "sell" else "0x0000000000000000000000000000000000000001"
    outgoing = "0x0000000000000000000000000000000000000001" if side == "sell" else token
    return {
        "data": {
            "swaps": [{
                "id": swap_id,
                "display": {"side": side},
                "inTokenAddress": incoming,
                "outTokenAddress": outgoing,
                "inNetworkId": chain,
                "outNetworkId": chain,
                "networkId": chain,
                "humanUsdAmountIn": usd,
                "createdAt": created,
                "provider": "DFLOW",
            }],
            "hasNextPage": True,
        }
    }


class FilterTests(unittest.TestCase):
    def test_unknown_mcap_liq_and_holders_cannot_pass_enabled_thresholds(self):
        store = new_store()
        item = swap(usd_in=80, side="buy")
        reasons = filter_reasons(item, store.settings)
        self.assertIn("mcap unknown", reasons)
        self.assertIn("liquidity unknown", reasons)
        self.assertFalse(allowed(item, store.settings))
        store.settings.min_mcap_usd = None
        store.settings.min_liq_usd = None
        self.assertTrue(allowed(item, store.settings))
        store.settings.min_holders = 5
        self.assertIn("holders unknown", filter_reasons(item, store.settings))
        self.assertFalse(allowed(item, store.settings))

    def test_missing_trade_amount_and_sell_toggle(self):
        store = new_store()
        store.settings.min_mcap_usd = None
        store.settings.min_liq_usd = None
        self.assertIn("trade amount unknown", filter_reasons(swap(usd_in=None), store.settings))
        self.assertFalse(allowed(swap(usd_in=10), store.settings))
        self.assertTrue(allowed(swap(usd_in=50), store.settings))
        store.settings.show_sells = False
        sold = swap(side="sell", usd_in=50, in_token=TOKEN, out_token=None, in_network_id=1399811149)
        self.assertIn("sells hidden", filter_reasons(sold, store.settings))
        unknown = swap(side=None, usd_in=50)
        self.assertIn("side unknown", filter_reasons(unknown, store.settings))
        self.assertIn("network unknown", filter_reasons(swap(usd_in=50, out_network_id=143, network_id=143), store.settings))


class MenuTests(unittest.TestCase):
    def test_owner_start_menu_and_second_start_edits(self):
        store = new_store()
        first = apply(store, message("/start"), now=NOW)
        self.assertEqual(first.kind, "send")
        self.assertIn("Monitoring is inactive", first.text)
        self.assertEqual(first.provider_calls, 0)
        from fomo_controls.store import bind_menu
        self.assertTrue(bind_menu(store, 10))
        self.assertFalse(bind_menu(store, 0))
        second = apply(store, message("/start"), now=NOW)
        self.assertEqual(second.kind, "edit")
        self.assertEqual(second.message_id, 10)

    def test_accounts_profile_links_search_pages_and_confirmed_delete(self):
        store = new_store()
        from fomo_controls.store import bind_menu
        bind_menu(store, 10)
        self.assertEqual([trader.handle for trader in store.traders], list(VERIFIED_FOLLOWS))
        self.assertTrue(all(trader.source == VERIFIED_SOURCE and not trader.seeded for trader in store.traders))
        added = apply(store, message("/add Alpha_1, @Beta.2\nbad!handle"), now=NOW)
        self.assertIn("Added 2", added.text)
        self.assertIn("Invalid 1", added.text)
        self.assertTrue(all(not trader.seeded for trader in store.traders if trader.handle in {"Alpha_1", "Beta.2"}))
        for extra in [f"Name{index}" for index in range(8)]:
            apply(store, message(f"/add {extra}"), now=NOW)
        self.assertEqual(len(store.traders), 14)
        page = apply(store, callback("a:p:1"), now=NOW)
        self.assertEqual(page.kind, "edit")
        self.assertEqual(page.message_id, 10)
        self.assertIn("@Name7", page.text)
        self.assertNotIn("@PressingProfits", page.text)
        found = apply(store, message("/search Press"), now=NOW)
        self.assertIn("@PressingProfits", found.text)
        self.assertNotIn("@bystevenr", found.text)
        self.assertIn("r=savipww", profile_url("PressingProfits"))
        urls = _urls(found.markup)
        self.assertTrue(urls)
        self.assertTrue(all("r=savipww" in url and "source=share_link" in url for url in urls))
        before = len(store.traders)
        ask = apply(store, callback("a:d:PressingProfits"), now=NOW)
        self.assertIn("Nothing is deleted yet", ask.text)
        self.assertEqual(len(store.traders), before)
        gone = apply(store, callback("a:y:PressingProfits"), now=NOW)
        self.assertNotIn("@PressingProfits", gone.text)
        ask_all = apply(store, callback("a:D"), now=NOW)
        self.assertIn("Nothing is deleted yet", ask_all.text)
        self.assertGreater(len(store.traders), 0)
        cleared = apply(store, callback("a:Y"), now=NOW)
        self.assertIn("0-0 / 0", cleared.text)
        restored = apply(store, callback("a:v"), now=NOW)
        self.assertIn("Not a fresh import", restored.text)
        self.assertEqual([trader.handle for trader in store.traders], list(VERIFIED_FOLLOWS))

    def test_non_owner_and_injection_have_no_side_effects(self):
        store = new_store()
        from fomo_controls.store import bind_menu
        bind_menu(store, 10)
        before = json.dumps(to_dict(store), sort_keys=True)
        cases = [
            message("/start", chat_id=111, from_id=111),
            message("/add Evil", chat_id=OWNER, from_id=222),
            callback("a:Y", chat_id=999, from_id=OWNER),
            callback("a:Y", chat_id=OWNER, from_id=222),
            callback("a:d:<script>alert(1)</script>"),
            callback("a:" + ("x" * 80)),
            callback("m:h", message_id=0),
            {"callback_query": {"data": "a:Y", "from": {"id": OWNER}}},
        ]
        for update in cases:
            effect = apply(store, update, now=NOW)
            self.assertEqual(effect.kind, "ignore")
            self.assertEqual(effect.text, "")
            self.assertEqual(effect.provider_calls, 0)
        self.assertEqual(json.dumps(to_dict(store), sort_keys=True), before)

    def test_resume_and_interval_do_not_start_polling(self):
        store = new_store()
        from fomo_controls.store import bind_menu
        bind_menu(store, 10)
        resumed = apply(store, callback("c:resume"), now=NOW)
        self.assertFalse(store.paused)
        self.assertIn("Monitoring: inactive", resumed.text)
        self.assertIn("does not start polling", resumed.text)
        self.assertIn("No monitoring budget is approved", resumed.text)
        self.assertIn("Last poll: never", resumed.text)
        apply(store, callback("f:i"), now=NOW)
        saved = apply(store, message("20"), now=NOW)
        self.assertEqual(store.settings.requested_interval_s, 20)
        self.assertIn("not running", saved.text)
        self.assertIn("No monitoring budget is approved", saved.text)
        russian = apply(store, callback("l:ru"), now=NOW)
        self.assertIn("Наблюдение не запущено", russian.text)
        self.assertIn("не запускает опрос", apply(store, callback("m:s"), now=NOW).text)

    def test_seed_snapshot_sends_nothing_and_ui_does_not_fetch(self):
        store = new_store()
        from fomo_controls.store import bind_menu
        bind_menu(store, 10)
        result = seed_snapshot(store, "PressingProfits", positions("id-1"))
        self.assertEqual(result["sends"], 0)
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["new_ids"], 1)
        again = seed_snapshot(store, "PressingProfits", positions("id-1"))
        self.assertEqual(again["new_ids"], 0)
        seen = store.find("PressingProfits").seen_ids
        apply(store, callback("f:m"), now=NOW)
        self.assertEqual(store.find("PressingProfits").seen_ids, seen)
        recent = apply(store, callback("m:r"), now=NOW)
        self.assertIn("does not read the provider", recent.text)
        self.assertEqual(recent.provider_calls, 0)
        self.assertIn("liquidity unknown", recent.text)
        self.assertNotIn("mcap unknown", recent.text)
        urls = _urls(recent.markup)
        self.assertTrue(any("chainId=1399811149" in url and "r=savipww" in url for url in urls))
        self.assertTrue(any("/profile/PressingProfits" in url and "r=savipww" in url for url in urls))

    def test_unknown_chain_recent_uses_signup_and_profile_ref(self):
        store = new_store()
        from fomo_controls.store import bind_menu
        bind_menu(store, 10)
        seed_snapshot(
            store,
            "@escobarpablo",
            positions("id-m", side="buy", chain=143, token=TOKEN),
        )
        store.settings.min_mcap_usd = None
        store.settings.min_liq_usd = None
        recent = apply(store, callback("r:w:24"), now=NOW)
        self.assertIn("Monad", recent.text)
        urls = _urls(recent.markup)
        self.assertIn(OPEN_FOMO_URL, urls)
        self.assertTrue(any("/profile/escobarpablo" in url and "r=savipww" in url for url in urls))
        self.assertNotIn("chainId=143", " ".join(urls))

    def test_import_is_unavailable_and_does_not_change_accounts(self):
        store = new_store()
        from fomo_controls.store import bind_menu
        bind_menu(store, 10)
        before = [trader.handle for trader in store.traders]
        effect = apply(store, callback("a:i"), now=NOW)
        self.assertIn("unavailable", effect.text)
        self.assertIn("not verified", effect.text)
        self.assertEqual([trader.handle for trader in store.traders], before)
        self.assertEqual(effect.provider_calls, 0)
        filters = apply(store, callback("m:f"), now=NOW)
        self.assertIn("not implemented", filters.text)

    def test_store_is_separate_from_desk_filenames(self):
        store = new_store()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "controls.json"
            save_store(path, store)
            loaded = load_store(path)
            self.assertEqual([trader.handle for trader in loaded.traders], list(VERIFIED_FOLLOWS))
            self.assertTrue(loaded.paused)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        repo = Path(__file__).resolve().parents[2]
        with self.assertRaises(Exception):
            save_store(repo / "d" / "controls.json", store)
        with self.assertRaises(Exception):
            save_store(Path("/tmp/state.json"), store)

    def test_package_does_not_poll_or_consume_updates(self):
        root = Path(__file__).resolve().parents[1]
        blob = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
        for needle in ("getUpdates", "setWebhook", "while True", "urlopen", "PUMPFOMO_API_KEY"):
            self.assertNotIn(needle, blob)
        text = transcript()
        self.assertIn("store_unchanged: True", text)
        self.assertIn("other account kind: ignore", text)
        self.assertIn("verified-follows-2026-11-07", text)
        self.assertIn("does not start polling", text)

    def test_bad_snapshot_does_not_mark_seeded(self):
        store = new_store()
        with self.assertRaises(ControlsError):
            seed_snapshot(store, "PressingProfits", {"data": {"userHandle": "x"}})
        self.assertFalse(store.find("PressingProfits").seeded)

    def test_set_market_cap_and_liquidity_without_a_lookup(self):
        store = new_store()
        from fomo_controls.store import bind_menu, from_dict
        bind_menu(store, 10)
        prompt = apply(store, callback("f:c"), now=NOW)
        self.assertIn("does not start a lookup", prompt.text)
        saved = apply(store, message("75000"), now=NOW)
        self.assertEqual(store.settings.min_mcap_usd, 75000)
        self.assertEqual(store.settings.mcap_amount_usd, 75000)
        self.assertIn("No collector", saved.text)
        apply(store, callback("f:m"), now=NOW)
        self.assertIsNone(store.settings.min_mcap_usd)
        apply(store, callback("f:m"), now=NOW)
        self.assertEqual(store.settings.min_mcap_usd, 75000)
        rejected = apply(store, callback("f:l"), now=NOW)
        self.assertEqual(apply(store, message("20.5"), now=NOW).text.startswith("Threshold was not"), True)
        self.assertEqual(store.settings.min_liq_usd, 20000)
        self.assertIn("does not start a lookup", rejected.text)
        old = {
            "version": 1,
            "paused": True,
            "language": "ru",
            "menu_message_id": 77,
            "monitoring": "inactive",
            "traders": [{
                "handle": "savipww",
                "source": "owner-added",
                "seeded": True,
                "seen_ids": ["keep-me"],
                "cached": [],
            }],
            "settings": {"min_trade_usd": 50, "min_mcap_usd": 50000, "min_liq_usd": 20000},
        }
        loaded = from_dict(old)
        self.assertEqual(loaded.menu_message_id, 77)
        self.assertEqual(loaded.language, "ru")
        self.assertTrue(loaded.paused)
        self.assertEqual(loaded.traders[0].handle, "savipww")
        self.assertEqual(loaded.traders[0].seen_ids, ["keep-me"])
        self.assertEqual(loaded.settings.min_mcap_usd, 50000)
        self.assertEqual(loaded.settings.mcap_amount_usd, 50000)
        self.assertEqual(loaded.settings.liq_amount_usd, 20000)


def _urls(markup):
    found = []
    for row in (markup or {}).get("inline_keyboard", []):
        for button in row:
            if "url" in button:
                found.append(button["url"])
    return found


if __name__ == "__main__":
    unittest.main()
