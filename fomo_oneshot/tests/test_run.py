"""Request cap, dry-run, owner send, seeding, and redaction."""

from __future__ import annotations

import json
import os
import tempfile
import traceback
import unittest
from pathlib import Path
from unittest import mock

import urllib.request

from fomo_oneshot.client import Budget, CapError, ProviderError, get_json, positions_url
from fomo_oneshot.client import _NoRedirect
from fomo_oneshot.constants import OWNER_CHAT_ID
from fomo_oneshot.engine import RunConfig, execute, render_report
from fomo_oneshot.guard import guarded_opener
from fomo_oneshot.redact import redact
from fomo_oneshot.seen import SeenError, assert_safe_seen_path
from fomo_oneshot.telegram import OwnerGuard, assert_owner, send_one
from fomo_oneshot.tests.test_mapping import load

TOKEN = "BtSvtGREKtTWuc5YMQE1SVHJsGCb5YCyFS8G73sypump"
SECRET = "pf_live_supersecret"
BOT = "123456:AAEsecret"


def telegram_ok(message_id: int = 7):
    body = json.dumps({"ok": True, "result": {"message_id": message_id}}).encode()
    return 200, body


def page(ids, *, has_next=False, token=TOKEN):
    swaps = []
    for index, swap_id in enumerate(ids):
        swaps.append(
            {
                "id": swap_id,
                "display": {"side": "sell"},
                "inTokenAddress": token,
                "inHumanAmount": index + 1,
                "networkId": 1399811149,
                "inNetworkId": 1399811149,
                "createdAt": "2026-11-07T01:46:05Z",
                "provider": "DFLOW",
            }
        )
    return {"data": {"swaps": swaps, "hasNextPage": has_next}}


class BudgetTests(unittest.TestCase):
    def test_cap_is_three_and_the_fourth_call_does_not_hit_transport(self):
        budget = Budget(99)
        self.assertEqual(budget.limit, 3)
        calls = []

        def transport(url, token):
            calls.append(url)
            return 200, b'{"data":{"swaps":[],"hasNextPage":true}}'

        for _ in range(3):
            get_json(positions_url("PressingProfits"), token="k", transport=transport, budget=budget)
        with self.assertRaises(CapError):
            get_json(positions_url("PressingProfits"), token="k", transport=transport, budget=budget)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all("cursor" not in url and "?" not in url for url in calls))

    def test_positions_url_has_no_query(self):
        self.assertEqual(
            positions_url("@PressingProfits"),
            "https://api.pumpfomo.com/v1/fomo/users/PressingProfits/positions",
        )

    def test_stop_statuses_are_not_retried_and_do_not_echo_secrets(self):
        for status, code in ((401, "missing_key"), (403, "scope_missing"), (402, "credits_exhausted"), (429, "rate_limited")):
            calls = []

            def transport(url, token, status=status, code=code):
                calls.append(url)
                body = json.dumps(
                    {"code": code, "message": f"Bearer {SECRET}", "upgrade": "https://pay.example/topup"}
                ).encode()
                return status, body

            budget = Budget(3)
            with self.assertRaises(ProviderError) as caught:
                get_json(positions_url("PressingProfits"), token=SECRET, transport=transport, budget=budget)
            self.assertEqual(len(calls), 1)
            text = str(caught.exception)
            self.assertNotIn(SECRET, text)
            self.assertNotIn("pay.example", text)
            self.assertNotIn("Bearer", text)
            self.assertIn(str(status), text)
            self.assertIn(code, text)
            if status == 402:
                self.assertIn("no upgrade and no top-up", text)

    def test_other_http_errors_are_single_attempt(self):
        calls = []

        def transport(url, token):
            calls.append(1)
            return 503, b'{"code":"upstream_busy","message":"retry"}'

        with self.assertRaises(ProviderError) as caught:
            get_json(positions_url("PressingProfits"), token="k", transport=transport, budget=Budget(3))
        self.assertEqual(calls, [1])
        self.assertIn("HTTP 503", str(caught.exception))
        self.assertNotIn("retry", str(caught.exception))

    def test_redirect_handler_does_not_include_the_target(self):
        handler = _NoRedirect()
        with self.assertRaises(ProviderError) as caught:
            handler.redirect_request(None, None, 302, "moved", {}, "https://evil.example/pf_live_secret")
        self.assertNotIn("evil.example", str(caught.exception))
        self.assertNotIn("pf_live", str(caught.exception))

    def test_redirect_does_not_open_the_next_url_or_keep_the_request(self):
        handler = _NoRedirect()
        opened = []

        class Parent:
            def open(self, *args, **kwargs):
                opened.append(args)
                raise AssertionError("followed redirect")

        handler.parent = Parent()
        request = urllib.request.Request(
            "https://api.pumpfomo.com/v1/fomo/users/PressingProfits/positions",
            headers={"Authorization": "Bearer pf_live_supersecret"},
            method="GET",
        )
        headers = {"location": "https://evil.example/steal?token=pf_live_supersecret"}
        for method in ("http_error_301", "http_error_302", "http_error_303", "http_error_307", "http_error_308"):
            with self.assertRaises(ProviderError) as caught:
                getattr(handler, method)(request, None, 302, "moved", headers)
            text = "".join(traceback.format_exception(caught.exception))
            self.assertNotIn("pf_live_supersecret", text)
            self.assertNotIn("evil.example", text)
            self.assertIsNone(caught.exception.__cause__)
            self.assertIsNone(caught.exception.__context__)
        self.assertEqual(opened, [])

    def test_env_proxy_is_not_installed(self):
        with mock.patch.dict(os.environ, {"https_proxy": "http://user:pw@proxy.example:8080", "http_proxy": "http://user:pw@proxy.example:8080"}):
            opener = guarded_opener(_NoRedirect())
        blob = " ".join(
            f"{type(handler).__name__} {getattr(handler, 'proxies', '')}" for handler in opener.handlers
        )
        self.assertNotIn("proxy.example", blob)
        self.assertNotIn("user:pw", blob)

    def test_transport_exception_and_bad_json_do_not_chain_secrets(self):
        secret = "pf_live_supersecret"

        def boom(url, token):
            raise OSError(f"Bearer {token} request {url}")

        with self.assertRaises(ProviderError) as caught:
            get_json(positions_url("PressingProfits"), token=secret, transport=boom, budget=Budget(3))
        text = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn(secret, text)
        self.assertNotIn(secret, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)

        def bad_json(url, token):
            return 200, f"not-json {secret}".encode()

        with self.assertRaises(ProviderError) as caught:
            get_json(positions_url("PressingProfits"), token=secret, transport=bad_json, budget=Budget(3))
        text = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn(secret, text)
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)


class RedactTests(unittest.TestCase):
    def test_bearer_key_and_bot_token_are_scrubbed(self):
        raw = (
            "Authorization: Bearer pf_live_supersecret failed "
            "https://api.telegram.org/bot123456:AAEsecret/sendMessage"
        )
        cleaned = redact(raw)
        self.assertNotIn("pf_live_supersecret", cleaned)
        self.assertNotIn("AAEsecret", cleaned)
        self.assertNotIn("bot123456:", cleaned)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.seen = Path(self.tmp.name) / "seen.json"

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, **kwargs):
        base = dict(
            handle="PressingProfits",
            replay=False,
            send=False,
            following=False,
            seen_path=self.seen,
            fixture=True,
            max_requests=3,
            api_key=None,
            telegram_token=None,
            positions_payload=load("sell_page.json"),
            following_payload=None,
        )
        base.update(kwargs)
        return RunConfig(**base)

    def test_dry_run_first_fetch_seeds_and_sends_nothing(self):
        def boom(*args, **kwargs):
            raise AssertionError("telegram was called")

        result = execute(self.config(send=True, telegram_token=BOT), send_transport=boom)
        report = render_report(result)
        self.assertEqual(result.sends, 0)
        self.assertIsNone(result.card_text)
        self.assertTrue(result.first_run)
        self.assertEqual(result.seen_count, 1)
        self.assertIn("sends: 0", report)
        self.assertNotIn(BOT, report)
        stored = json.loads(self.seen.read_text(encoding="utf-8"))
        self.assertTrue(stored["handles"]["pressingprofits"]["seeded"])
        self.assertEqual(stored["handles"]["pressingprofits"]["ids"], ["fixture-sell-1"])
        self.assertEqual(self.seen.stat().st_mode & 0o777, 0o600)
        again = execute(self.config(), send_transport=boom)
        self.assertEqual(again.sends, 0)
        self.assertIsNone(again.card_text)
        self.assertFalse(again.first_run)

    def test_replay_is_labeled_and_does_not_flood_on_the_next_default_run(self):
        result = execute(self.config(replay=True))
        report = render_report(result)
        self.assertEqual(result.sends, 0)
        self.assertEqual(result.requests, [])
        self.assertIn("TEST / HISTORICAL", result.card_text)
        self.assertIn("FIXTURE — not a live capture and not data verification.", result.card_text)
        self.assertIn("Historical replay of one fetched swap.", result.card_text)
        self.assertIn("sold 20973102.33", result.card_text)
        self.assertIn("received 186.206", result.card_text)
        self.assertIn("USD 186.21", result.card_text)
        self.assertIn("price 0.00000898841", result.card_text)
        self.assertIn("Solana 1399811149", result.card_text)
        self.assertIn("Nov 6 21:46:05 AST", result.card_text)
        self.assertIn("source time 2026-11-07T01:46:05Z", result.card_text)
        self.assertTrue(report.endswith(result.card_text + "\n"))
        self.assertIn(f"button: Open FOMO {result.button_url}", report)
        self.assertIn("r=savipww", result.button_url)
        self.assertIn("source=share_link", result.button_url)
        follow = execute(self.config())
        self.assertIsNone(follow.card_text)
        self.assertEqual(follow.sends, 0)

    def test_replay_send_is_one_owner_message_and_default_send_is_not(self):
        calls = []

        def transport(token, payload):
            calls.append((token, payload))
            return telegram_ok(15)

        result = execute(
            self.config(replay=True, send=True, telegram_token=BOT),
            send_transport=transport,
        )
        self.assertEqual(result.sends, 1)
        self.assertEqual(len(calls), 1)
        token, payload = calls[0]
        self.assertEqual(token, BOT)
        self.assertEqual(payload["chat_id"], OWNER_CHAT_ID)
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertTrue(payload["disable_web_page_preview"])
        keyboard = payload["reply_markup"]["inline_keyboard"]
        self.assertEqual(len(keyboard), 1)
        self.assertEqual(len(keyboard[0]), 1)
        self.assertEqual(keyboard[0][0]["text"], "Open FOMO")
        self.assertNotIn("callback_data", keyboard[0][0])
        self.assertIn("<b>TEST / HISTORICAL</b>", payload["text"])
        self.assertNotIn(BOT, render_report(result))

    def test_later_page_sends_only_the_newest_unseen_card(self):
        execute(self.config(positions_payload=page(["old-1", "old-2"])))
        calls = []

        def transport(token, payload):
            calls.append(payload)
            return telegram_ok(16)

        payload = page(["new-1", "new-2", "old-1"])
        result = execute(
            self.config(send=True, telegram_token=BOT, positions_payload=payload),
            send_transport=transport,
        )
        self.assertEqual(result.sends, 1)
        self.assertEqual(result.candidate_id, "new-1")
        self.assertEqual(result.deferred_unseen, 1)
        self.assertEqual(len(calls), 1)
        stored = json.loads(self.seen.read_text(encoding="utf-8"))
        self.assertEqual(stored["handles"]["pressingprofits"]["ids"], ["old-1", "old-2", "new-1"])
        second = execute(
            self.config(send=True, telegram_token=BOT, positions_payload=payload),
            send_transport=transport,
        )
        self.assertEqual(second.candidate_id, "new-2")
        self.assertEqual(second.sends, 1)
        self.assertEqual(len(calls), 2)

    def test_dry_run_of_a_new_swap_does_not_mark_it_seen(self):
        execute(self.config(positions_payload=page(["old-1"])))
        result = execute(self.config(fixture=False, positions_payload=page(["new-1", "old-1"])))
        self.assertEqual(result.sends, 0)
        self.assertEqual(result.candidate_id, "new-1")
        self.assertIsNotNone(result.card_text)
        self.assertIn("Historical record from one fetched page.", result.card_text)
        self.assertNotIn("FIXTURE", result.card_text)
        stored = json.loads(self.seen.read_text(encoding="utf-8"))
        self.assertEqual(stored["handles"]["pressingprofits"]["ids"], ["old-1"])

    def test_has_next_page_does_not_cause_another_request(self):
        calls = []

        def transport(url, token):
            calls.append(url)
            if url.endswith("/following"):
                body = json.dumps({"data": {"users": [{"userHandle": "savipww"}], "hasNextPage": True}}).encode()
            else:
                body = json.dumps(page(["a-1"], has_next=True)).encode()
            return 200, body

        result = execute(
            self.config(fixture=False, positions_payload=None, api_key=SECRET, following=True),
            transport=transport,
        )
        self.assertEqual(calls, [
            "https://api.pumpfomo.com/v1/fomo/users/PressingProfits/positions",
            "https://api.pumpfomo.com/v1/fomo/users/PressingProfits/following",
        ])
        self.assertTrue(result.has_next_page)
        self.assertEqual(result.sends, 0)
        self.assertEqual(result.following_handles, ("savipww",))
        report = render_report(result)
        self.assertNotIn(SECRET, report)
        self.assertNotIn("[redacted]", report)

    def test_request_cap_skips_following_and_stops_on_429_without_sending(self):
        calls = []

        def ok(url, token):
            calls.append(url)
            return 200, json.dumps(page(["a-1"])).encode()

        capped = execute(
            self.config(fixture=False, positions_payload=None, api_key="k", following=True, max_requests=1),
            transport=ok,
        )
        self.assertEqual(len(calls), 1)
        self.assertIn("request cap", capped.following_note)
        self.assertEqual(capped.request_cap, 1)
        calls.clear()

        def limited(url, token):
            calls.append(url)
            return 429, json.dumps({"error": {"code": "rate_limited", "token": SECRET}}).encode()

        fresh = self.seen.with_name("fresh.json")
        stopped = execute(
            self.config(
                fixture=False,
                positions_payload=None,
                api_key=SECRET,
                following=True,
                send=True,
                telegram_token=BOT,
                seen_path=fresh,
            ),
            transport=limited,
            send_transport=lambda *args: (_ for _ in ()).throw(AssertionError("sent")),
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(stopped.sends, 0)
        self.assertFalse(fresh.exists())
        report = render_report(stopped)
        self.assertIn("HTTP 429 rate_limited; stopped", report)
        self.assertNotIn(SECRET, report)
        self.assertNotIn(BOT, report)

    def test_following_failure_does_not_seed_or_send(self):
        calls = []

        def transport(url, token):
            calls.append(url)
            if url.endswith("/positions"):
                return 200, json.dumps(page(["a-1"], has_next=True)).encode()
            return 402, b'{"code":"credits_exhausted","upgrade":"https://pay.example"}'

        result = execute(
            self.config(fixture=False, positions_payload=None, api_key="k", following=True),
            transport=transport,
        )
        self.assertEqual(len(calls), 2)
        self.assertIn("no upgrade and no top-up", result.stopped)
        self.assertEqual(result.sends, 0)
        self.assertFalse(self.seen.exists())

    def test_fixture_following_flag_does_not_call_transport(self):
        def transport(url, token):
            raise AssertionError(url)

        result = execute(self.config(following=True), transport=transport)
        self.assertEqual(result.requests, [])
        self.assertIn("fixture", result.following_note)

    def test_send_failure_does_not_mark_the_new_id(self):
        execute(self.config(positions_payload=page(["old-1"])))

        def transport(token, payload):
            return 500

        result = execute(
            self.config(send=True, telegram_token=BOT, positions_payload=page(["new-1", "old-1"])),
            send_transport=transport,
        )
        self.assertEqual(result.sends, 0)
        self.assertIn("telegram HTTP 500", result.stopped)
        stored = json.loads(self.seen.read_text(encoding="utf-8"))
        self.assertEqual(stored["handles"]["pressingprofits"]["ids"], ["old-1"])

    def test_malformed_telegram_json_is_unconfirmed_and_not_resent(self):
        from fomo_oneshot.telegram import interpret_send_response

        secret = "pf_live_in_body"
        cases = [
            (200, b"not-json"),
            (200, json.dumps({"ok": False, "description": secret}).encode()),
            (200, json.dumps({"ok": True}).encode()),
            (200, json.dumps({"ok": True, "result": {"message_id": 0}}).encode()),
            (200, json.dumps({"ok": True, "result": {"message_id": -3}}).encode()),
            (200, json.dumps({"ok": True, "result": {"message_id": "12"}}).encode()),
            (200, json.dumps({"ok": True, "result": {"message_id": True}}).encode()),
            (200, None),
        ]
        for status, body in cases:
            receipt = interpret_send_response(status, body)
            self.assertFalse(receipt.confirmed)
            self.assertIsNone(receipt.message_id)
        good = interpret_send_response(200, json.dumps({"ok": True, "result": {"message_id": 42, "text": secret}}).encode())
        self.assertTrue(good.confirmed)
        self.assertEqual(good.message_id, 42)
        self.assertNotIn(secret, str(good))

        execute(self.config(positions_payload=page(["old-1"])))
        calls = []

        def transport(token, payload):
            calls.append(1)
            return 200, json.dumps({"ok": True, "result": {"message_id": "nope"}, "token": secret}).encode()

        result = execute(
            self.config(send=True, telegram_token=BOT, positions_payload=page(["new-1", "old-1"])),
            send_transport=transport,
        )
        self.assertEqual(calls, [1])
        self.assertEqual(result.sends, 0)
        self.assertIn("unconfirmed", result.stopped or "")
        self.assertIn("not resent", result.stopped or "")
        self.assertNotIn(secret, result.stopped or "")
        stored = json.loads(self.seen.read_text(encoding="utf-8"))
        self.assertEqual(stored["handles"]["pressingprofits"]["ids"], ["old-1"])

    def test_owner_guard_rejects_other_chats_before_transport(self):
        self.assertEqual(assert_owner(OWNER_CHAT_ID), OWNER_CHAT_ID)
        self.assertEqual(assert_owner(str(OWNER_CHAT_ID)), OWNER_CHAT_ID)
        for other in (1, "1", None, True, OWNER_CHAT_ID + 1, float(OWNER_CHAT_ID)):
            with self.assertRaises(OwnerGuard):
                assert_owner(other)

        def transport(token, payload):
            raise AssertionError("sent")

        from fomo_oneshot.card import build_card
        from fomo_oneshot.tests.test_mapping import swap

        card = build_card(handle="PressingProfits", swap=swap(), fixture=True, replay=True)
        with self.assertRaises(OwnerGuard):
            send_one(token=BOT, card=card, transport=transport, chat_id=1)

    def test_html_escapes_card_text(self):
        captured = {}

        def transport(token, payload):
            captured.update(payload)
            return telegram_ok(17)

        nasty = page(["new-1"])
        nasty["data"]["swaps"][0]["provider"] = "DFLOW <tag> & co"
        execute(self.config(positions_payload=page(["old-1"])))
        execute(
            self.config(send=True, telegram_token=BOT, positions_payload=nasty),
            send_transport=transport,
        )
        self.assertIn("DFLOW &lt;tag&gt; &amp; co", captured["text"])
        self.assertNotIn("<tag>", captured["text"])

    def test_row_cap_keeps_only_the_first_page_slice(self):
        ids = [f"id-{index}" for index in range(60)]
        result = execute(self.config(positions_payload=page(ids)))
        self.assertTrue(result.truncated)
        self.assertEqual(result.seen_count, 50)
        stored = json.loads(self.seen.read_text(encoding="utf-8"))
        saved = stored["handles"]["pressingprofits"]["ids"]
        self.assertEqual(saved[0], "id-0")
        self.assertEqual(saved[-1], "id-49")
        self.assertNotIn("id-59", saved)

    def test_seen_path_inside_published_data_does_not_fetch_or_write(self):
        repo = Path(__file__).resolve().parents[2]
        target = repo / "d" / "fomo-oneshot-should-not-exist.json"
        calls = []

        def transport(url, token):
            calls.append(url)
            return 200, b"{}"

        try:
            result = execute(
                self.config(
                    fixture=False,
                    positions_payload=None,
                    api_key="pf_live_supersecret",
                    seen_path=target,
                    replay=True,
                    send=True,
                    telegram_token=BOT,
                ),
                transport=transport,
                send_transport=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("sent")),
            )
            self.assertEqual(calls, [])
            self.assertEqual(result.sends, 0)
            self.assertFalse(target.exists())
            self.assertIn("published desk", result.stopped or "")
            self.assertNotIn("pf_live_supersecret", render_report(result))
        finally:
            if target.exists():
                target.unlink()

    def test_seen_store_cannot_replace_published_desk_files(self):
        repo = Path(__file__).resolve().parents[2]
        with self.assertRaises(SeenError):
            assert_safe_seen_path(repo / "d" / "state.json")
        with self.assertRaises(SeenError):
            assert_safe_seen_path(Path("/tmp/state.json"))

    def test_package_sources_do_not_wire_a_scheduler_or_the_desk_db(self):
        root = Path(__file__).resolve().parents[1]
        blob = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
        for needle in ("sqlite3", "/workspace/desk", "systemd", "crontab", "apscheduler", "while True"):
            self.assertNotIn(needle, blob)
        self.assertIn('"state.json"', (root / "seen.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
