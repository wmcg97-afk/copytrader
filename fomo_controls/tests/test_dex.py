"""DEX Screener enrichment from the saved public sample. No live HTTP."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fomo_controls.dex import (
    BASE_URL,
    MarketCache,
    build_url,
    evm_canonical,
    format_market_note,
    process_candidate,
    select_pool,
    urllib_transport,
)
from fomo_controls.dex import _NoRedirect
from fomo_controls.filters import allowed, filter_reasons
from fomo_oneshot.guard import guarded_opener
from fomo_oneshot.swap import Swap

TOKEN = "BtSvtGREKtTWuc5YMQE1SVHJsGCb5YCyFS8G73sypump"
FETCHED = datetime(2026, 11, 7, 19, 46, 18, tzinfo=timezone.utc)
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "dexscreener_btsvt_solana.json"


def load_pairs():
    return json.loads(FIXTURE.read_text(encoding="utf-8"), parse_float=Decimal)


def sell_swap(**kwargs) -> Swap:
    base = dict(
        id="fixture-sell-1",
        side="sell",
        created_at="2026-11-07T01:46:05Z",
        provider="DFLOW",
        network_id=1399811149,
        in_network_id=1399811149,
        out_network_id=1399811149,
        in_token=TOKEN,
        out_token="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        in_amount=Decimal("20973102.33"),
        out_amount=Decimal("186.206"),
        usd_in=Decimal("186.21"),
        usd_out=None,
        price=Decimal("0.00000898841"),
        is_off_platform=None,
        is_crossmint=None,
        address=None,
        recipient=None,
        in_trade_id=None,
        out_trade_id=None,
    )
    base.update(kwargs)
    return Swap(**base)


class SampleTests(unittest.TestCase):
    def test_public_sample_fails_default_cap_and_liquidity(self):
        calls = []

        def transport(url):
            calls.append(url)
            return 200, FIXTURE.read_bytes()

        snapshot = process_candidate(sell_swap(), now=FETCHED, transport=transport, cache=MarketCache())
        self.assertEqual(calls, [f"{BASE_URL}/token-pairs/v1/solana/{TOKEN}"])
        self.assertEqual(snapshot.pair_address, "2qW4UmdbvQvsmxaepdfA5Bm6VbUuf1sR996J7JTVhbFL")
        self.assertEqual(snapshot.market_cap, Decimal(3593))
        self.assertEqual(snapshot.liquidity_usd, Decimal("3348.53"))
        self.assertEqual(snapshot.fdv, Decimal(3593))
        settings = __import__("fomo_controls.store", fromlist=["Settings"]).Settings()
        reasons = filter_reasons(sell_swap(), settings, snapshot)
        self.assertIn("below min mcap", reasons)
        self.assertIn("below min liquidity", reasons)
        self.assertNotIn("mcap unknown", reasons)
        self.assertNotIn("below min trade", reasons)
        self.assertFalse(allowed(sell_swap(), settings, snapshot))
        note = format_market_note(snapshot, now=FETCHED, min_mcap=50000, min_liq=20000)
        self.assertIn("Not the value at the swap source time", note)
        self.assertIn("not a historical threshold pass", note)
        self.assertIn("fdv 3593 (not used for the market cap check)", note)
        self.assertIn("fetched_at 2026-11-07T19:46:18Z", note)

    def test_fdv_cannot_satisfy_market_cap(self):
        pair = {
            "chainId": "solana",
            "pairAddress": "pair-a",
            "baseToken": {"address": TOKEN},
            "quoteToken": {"address": "So11111111111111111111111111111111111111112"},
            "liquidity": {"usd": Decimal(100000)},
            "fdv": Decimal(100000),
        }
        selected = select_pool([pair], TOKEN)
        self.assertIsNone(selected["market_cap"])
        self.assertEqual(selected["fdv"], Decimal(100000))
        self.assertEqual(selected["liquidity_usd"], Decimal(100000))


class SelectionTests(unittest.TestCase):
    def test_highest_liquidity_wins_and_is_not_summed(self):
        low = _pair("pair-b", TOKEN, 1000, 10)
        high = _pair("pair-a", TOKEN, 2500, 20)
        quote_only = _pair("pair-q", "So11111111111111111111111111111111111111112", 999999, 1)
        quote_only["quoteToken"] = {"address": TOKEN}
        wrong = _pair("pair-w", TOKEN, 999999, 1)
        wrong["chainId"] = "ethereum"
        mismatch = _pair("pair-c", TOKEN.lower(), 999999, 1)
        selected = select_pool([low, high, quote_only, wrong, mismatch, "nope"], TOKEN)
        self.assertEqual(selected["pair_address"], "pair-a")
        self.assertEqual(selected["liquidity_usd"], Decimal(2500))
        self.assertNotEqual(selected["liquidity_usd"], Decimal(3500))

    def test_tie_uses_pair_address_order(self):
        selected = select_pool([
            _pair("pair-b", TOKEN, 10, 1),
            _pair("pair-a", TOKEN, 10, 2),
        ], TOKEN)
        self.assertEqual(selected["pair_address"], "pair-a")
        self.assertEqual(selected["market_cap"], Decimal(2))

    def test_zero_is_known_and_negative_or_text_is_unknown(self):
        zero = select_pool([_pair("pair-z", TOKEN, 0, 0)], TOKEN)
        self.assertEqual(zero["market_cap"], Decimal(0))
        self.assertEqual(zero["liquidity_usd"], Decimal(0))
        self.assertIsNone(select_pool([_pair("pair-n", TOKEN, -1, 10)], TOKEN))
        text = _pair("pair-t", TOKEN, 10, 10)
        text["marketCap"] = "3593"
        selected = select_pool([text], TOKEN)
        self.assertIsNone(selected["market_cap"])
        self.assertEqual(selected["liquidity_usd"], Decimal(10))


class CacheAndSecurityTests(unittest.TestCase):
    def test_cache_hold_and_single_attempt(self):
        calls = []

        def transport(url):
            calls.append(url)
            return 200, FIXTURE.read_bytes()

        cache = MarketCache()
        first = process_candidate(sell_swap(), now=FETCHED, transport=transport, cache=cache)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first.market_cap, Decimal(3593))
        second = process_candidate(sell_swap(), now=FETCHED + timedelta(seconds=10), transport=transport, cache=cache)
        self.assertEqual(len(calls), 1)
        self.assertEqual(second.fetched_at, first.fetched_at)
        process_candidate(sell_swap(), now=FETCHED + timedelta(seconds=45), transport=transport, cache=cache)
        self.assertEqual(len(calls), 2)

        failed = []

        def once(url):
            failed.append(url)
            return 500, b'{"secret":"pf_live_secret"}'

        missed = process_candidate(sell_swap(in_token="So11111111111111111111111111111111111111112"), now=FETCHED, transport=once, cache=MarketCache())
        self.assertEqual(failed, [f"{BASE_URL}/token-pairs/v1/solana/So11111111111111111111111111111111111111112"])
        self.assertIsNone(missed.market_cap)
        self.assertNotIn("pf_live", format_market_note(missed, now=FETCHED, min_mcap=50000, min_liq=20000))

    def test_stale_cache_can_be_refreshed_once(self):
        calls = []

        def transport(url):
            calls.append(1)
            return 200, FIXTURE.read_bytes()

        cache = MarketCache()
        process_candidate(sell_swap(), now=FETCHED, transport=transport, cache=cache)
        process_candidate(sell_swap(), now=FETCHED + timedelta(seconds=45), transport=transport, cache=cache)
        self.assertEqual(calls, [1, 1])

    def test_unsupported_chain_and_bad_address_make_no_request(self):
        def transport(url):
            raise AssertionError(url)

        base = process_candidate(
            sell_swap(in_network_id=8453, network_id=8453),
            now=FETCHED,
            transport=transport,
        )
        self.assertEqual(base.coverage, "unsupported-chain")
        self.assertEqual(
            evm_canonical("0x00000000000000000000000000000000000000AB"),
            "0x00000000000000000000000000000000000000ab",
        )
        bad = process_candidate(sell_swap(in_token="https://evil.example/token"), now=FETCHED, transport=transport)
        self.assertEqual(bad.coverage, "invalid-address")
        with self.assertRaises(Exception):
            build_url("../secrets")
        with self.assertRaises(Exception):
            urllib_transport("https://evil.example/token-pairs/v1/solana/" + TOKEN)

    def test_redirect_and_proxy_do_not_forward(self):
        handler = _NoRedirect()
        opened = []

        class Parent:
            def open(self, *args, **kwargs):
                opened.append(args)

        handler.parent = Parent()
        with self.assertRaises(Exception) as caught:
            handler.http_error_302(None, None, 302, "moved", {"location": "https://evil.example/pf_live_secret"})
        self.assertIn("redirect", str(caught.exception))
        self.assertNotIn("evil.example", str(caught.exception))
        self.assertEqual(opened, [])
        opener = guarded_opener(_NoRedirect())
        blob = " ".join(f"{type(item).__name__} {getattr(item, 'proxies', '')}" for item in opener.handlers)
        self.assertNotIn("proxy", blob.lower())


def _pair(pair_address, base, liquidity, cap):
    return {
        "chainId": "solana",
        "pairAddress": pair_address,
        "baseToken": {"address": base},
        "quoteToken": {"address": "So11111111111111111111111111111111111111112"},
        "liquidity": {"usd": Decimal(liquidity)},
        "marketCap": Decimal(cap),
        "fdv": Decimal(999999),
    }


if __name__ == "__main__":
    unittest.main()
