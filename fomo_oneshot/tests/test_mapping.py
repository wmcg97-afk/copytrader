"""Buy, sell, malformed, and unknown swap mapping."""

from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path

from fomo_oneshot.card import build_card
from fomo_oneshot.constants import OPEN_FOMO_URL
from fomo_oneshot.links import fomo_url
from fomo_oneshot.swap import Swap, parse_following, parse_positions

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"), parse_float=Decimal)


def swap(**kwargs) -> Swap:
    base = dict(
        id="swap-1",
        side="sell",
        created_at=None,
        provider=None,
        network_id=None,
        in_network_id=None,
        out_network_id=None,
        in_token=None,
        out_token=None,
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


class MappingTests(unittest.TestCase):
    def test_verified_shape_sell_keeps_amounts_and_does_not_invent_fields(self):
        page = parse_positions(load("sell_page.json"))
        self.assertIsNone(page.note)
        self.assertFalse(page.has_next_page)
        item = page.swaps[0]
        self.assertEqual(item.side, "sell")
        self.assertEqual(item.in_token, "BtSvtGREKtTWuc5YMQE1SVHJsGCb5YCyFS8G73sypump")
        self.assertIsNone(item.out_token)
        self.assertEqual(item.in_amount, Decimal("20973102.33"))
        self.assertEqual(item.out_amount, Decimal("186.206"))
        self.assertEqual(item.usd_in, Decimal("186.21"))
        self.assertIsNone(item.usd_out)
        self.assertEqual(item.price, Decimal("0.00000898841"))
        self.assertEqual(item.network_id, 1399811149)
        self.assertEqual(item.in_network_id, 1399811149)
        self.assertEqual(item.provider, "DFLOW")
        self.assertEqual(item.created_at, "2026-11-07T01:46:05Z")
        self.assertIsNone(item.address)
        self.assertIsNone(item.is_off_platform)
        self.assertEqual(item.traded_token, item.in_token)
        card = build_card(handle="PressingProfits", swap=item, fixture=True, replay=True)
        self.assertNotIn("USDC", card.text)
        self.assertNotIn("market cap", card.text.lower())
        self.assertNotIn("liquidity", card.text.lower())
        self.assertNotIn("holders", card.text.lower())
        self.assertNotIn("pnl", card.text.lower())
        self.assertIn("Not a live buy or sell signal. Not a recommendation.", card.text)

    def test_buy_uses_out_token_and_display_side_only(self):
        page = parse_positions(load("buy_page.json"))
        item = page.swaps[0]
        self.assertEqual(item.side, "buy")
        self.assertTrue(page.has_next_page)
        self.assertEqual(item.traded_token, "0x1111111111111111111111111111111111111111")
        self.assertEqual(item.token_network_id, 8453)
        self.assertEqual(item.in_amount, Decimal("10.5"))
        self.assertEqual(item.out_amount, Decimal(4))
        self.assertFalse(item.is_off_platform)
        card = build_card(handle="PressingProfits", swap=item, fixture=True, replay=False)
        self.assertIn("\nbuy\n", card.text)
        self.assertIn("spent 10.5\n", card.text)
        self.assertIn("received 4\n", card.text)
        self.assertNotIn("sold ", card.text)
        self.assertNotIn("off-platform", card.text)
        self.assertNotIn("on-platform", card.text)

    def test_malformed_and_unknown_rows_stay_null(self):
        page = parse_positions(load("malformed_page.json"))
        self.assertEqual(page.skipped_malformed, 1)
        by_id = {item.id: item for item in page.swaps}
        self.assertIsNone(by_id["bad-display"].side)
        self.assertIsNone(by_id["bad-display"].in_amount)
        self.assertIsNone(by_id["bad-display"].network_id)
        self.assertIsNone(by_id["bad-side"].side)
        self.assertEqual(by_id["bad-side"].in_token, "BtSvtGREKtTWuc5YMQE1SVHJsGCb5YCyFS8G73sypump")
        self.assertIsNone(by_id["bad-side"].traded_token)
        bad_types = by_id["bad-types"]
        self.assertEqual(bad_types.side, "sell")
        self.assertIsNone(bad_types.in_amount)
        self.assertIsNone(bad_types.out_amount)
        self.assertIsNone(bad_types.network_id)
        self.assertIsNone(bad_types.in_token)
        self.assertEqual(bad_types.provider, "OK")
        self.assertEqual(bad_types.created_at, "not-a-time")
        unknown = by_id["unknown-chain"]
        self.assertEqual(unknown.side, "buy")
        self.assertEqual(unknown.token_network_id, 1)
        self.assertIsNone(unknown.in_amount)
        self.assertIsNone(unknown.usd_in)
        self.assertIsNone(unknown.price)
        self.assertIsNone(unknown.created_at)
        self.assertEqual(unknown.address, "NOT_A_HANDLE_WALLET")
        card = build_card(handle="PressingProfits", swap=unknown, fixture=True, replay=True)
        self.assertNotIn("NOT_A_HANDLE_WALLET", card.text)
        self.assertIn("side unknown", build_card(handle="PressingProfits", swap=by_id["bad-side"], fixture=False, replay=False).text)
        self.assertNotIn("\nsold ", build_card(handle="PressingProfits", swap=by_id["bad-side"], fixture=False, replay=False).text)
        self.assertEqual(fomo_url(unknown), OPEN_FOMO_URL)
        self.assertEqual(fomo_url(by_id["bad-side"]), OPEN_FOMO_URL)

    def test_wallet_address_is_not_a_handle_or_a_coin_link(self):
        item = swap(
            side="sell",
            address="So11111111111111111111111111111111111111112",
            network_id=1399811149,
            in_token=None,
        )
        self.assertIsNone(item.traded_token)
        self.assertEqual(fomo_url(item), OPEN_FOMO_URL)
        text = build_card(handle="PressingProfits", swap=item, fixture=False, replay=True).text
        self.assertNotIn("So111", text)
        self.assertNotIn("@So111", text)

    def test_missing_object_shape_is_not_guessed(self):
        page = parse_positions({"data": {"userHandle": "PressingProfits", "following": 4}})
        self.assertEqual(page.swaps, ())
        self.assertIn("not guessed", page.note or "")
        handles, note = parse_following({"data": {"userHandle": "CivilNewCanid", "following": 4}})
        self.assertIsNone(handles)
        self.assertIn("data.users", note or "")

    def test_documented_wrapper_uses_data_swaps_and_display_side(self):
        payload = {
            "data": {
                "swaps": [
                    {
                        "id": "fixture-wrapper-buy",
                        "address": "not-a-handle",
                        "networkId": 8453,
                        "inTokenAddress": "0x0000000000000000000000000000000000000001",
                        "outTokenAddress": "BtSvtGREKtTWuc5YMQE1SVHJsGCb5YCyFS8G73sypump",
                        "inHumanAmount": 10,
                        "outHumanAmount": 20,
                        "humanUsdAmountIn": 10,
                        "humanUsdAmountOut": None,
                        "displayPriceUsd": 0.5,
                        "display": {"side": "buy"},
                        "createdAt": "2026-10-21T18:14:40.000Z",
                        "provider": "DFLOW",
                        "isOffPlatform": False,
                        "isCrossmint": False,
                        "inNetworkId": 8453,
                        "outNetworkId": 1399811149,
                        "recipient": None,
                        "inTradeId": None,
                        "outTradeId": None,
                    }
                ],
                "hasNextPage": True,
            },
            "meta": {"source": "fomo.family", "cache": "live", "fetchedAt": "2026-10-25T23:11:34.065Z"},
        }
        page = parse_positions(payload)
        self.assertIsNone(page.note)
        self.assertTrue(page.has_next_page)
        item = page.swaps[0]
        self.assertEqual(item.side, "buy")
        self.assertEqual(item.traded_token, "BtSvtGREKtTWuc5YMQE1SVHJsGCb5YCyFS8G73sypump")
        self.assertEqual(item.token_network_id, 1399811149)
        self.assertNotEqual(item.traded_token, item.address)
        self.assertTrue(item.cross_chain)

    def test_following_fixture_uses_user_handle_only(self):
        handles, note = parse_following(load("following_page.json"))
        self.assertIsNone(note)
        self.assertEqual(handles, ("PressingProfits", "bystevenr", "escobarpablo", "savipww"))

    def test_usd_difference_is_preserved(self):
        item = swap(side="buy", usd_in=Decimal("1.25"), usd_out=Decimal("1.5"), out_token="0x1111111111111111111111111111111111111111", out_network_id=8453)
        text = build_card(handle="PressingProfits", swap=item, fixture=False, replay=False).text
        self.assertIn("USD in 1.25 / USD out 1.5", text)

    def test_off_platform_true_is_labeled_and_null_is_omitted(self):
        on_card = build_card(handle="PressingProfits", swap=swap(is_off_platform=True, side="sell"), fixture=False, replay=True)
        self.assertIn("off-platform", on_card.text)
        off_card = build_card(handle="PressingProfits", swap=swap(is_off_platform=None, side="sell"), fixture=False, replay=True)
        self.assertNotIn("off-platform", off_card.text)

    def test_source_time_converts_to_ast_without_inventing_a_zone(self):
        item = swap(side="sell", created_at="2026-11-07T01:46:05Z", in_token="BtSvtGREKtTWuc5YMQE1SVHJsGCb5YCyFS8G73sypump", in_network_id=1399811149)
        text = build_card(handle="PressingProfits", swap=item, fixture=False, replay=True).text
        self.assertIn("source time 2026-11-07T01:46:05Z", text)
        self.assertIn("Nov 6 21:46:05 AST", text)
        millis = swap(side="sell", created_at="2026-11-07T01:46:05.000Z")
        self.assertIn("Nov 6 21:46:05 AST", build_card(handle="PressingProfits", swap=millis, fixture=False, replay=False).text)
        naive = swap(side="sell", created_at="2026-11-07T01:46:05")
        naive_text = build_card(handle="PressingProfits", swap=naive, fixture=False, replay=False).text
        self.assertIn("source time 2026-11-07T01:46:05", naive_text)
        self.assertIn("local time unknown", naive_text)
        self.assertNotIn("AST", naive_text)


if __name__ == "__main__":
    unittest.main()
