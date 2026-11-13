"""Coin links follow the published desk shape. Unknown chains use the invite URL."""

from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlsplit

from fomo_oneshot.constants import OPEN_FOMO_URL
from fomo_oneshot.links import fomo_url
from fomo_oneshot.tests.test_mapping import swap

TOKEN = "BtSvtGREKtTWuc5YMQE1SVHJsGCb5YCyFS8G73sypump"
EVM = "0x1111111111111111111111111111111111111111"


class LinkTests(unittest.TestCase):
    def test_supported_chains_use_repo_coin_shape_and_mandatory_share_params(self):
        cases = (
            ("sell", TOKEN, 1399811149, None),
            ("buy", EVM, 8453, 8453),
            ("buy", EVM, 56, 56),
            ("sell", TOKEN, 4663, 4663),
        )
        for side, token, chain, out_chain in cases:
            item = swap(
                side=side,
                in_token=token if side == "sell" else EVM,
                out_token=token if side == "buy" else None,
                in_network_id=chain if side == "sell" else 8453,
                out_network_id=out_chain if side == "buy" else chain,
                network_id=1399811149,
            )
            if side == "buy":
                item = swap(side="buy", out_token=token, out_network_id=chain, in_network_id=1, network_id=1)
            split = urlsplit(fomo_url(item))
            self.assertEqual(split.scheme, "https")
            self.assertEqual(split.netloc, "fomo.family")
            self.assertEqual(split.path, "/coin")
            query = parse_qs(split.query)
            self.assertEqual(query["address"], [token])
            self.assertEqual(query["chainId"], [str(chain)])
            self.assertEqual(query["r"], ["savipww"])
            self.assertEqual(query["source"], ["share_link"])
            self.assertEqual(
                split.query,
                f"address={token}&chainId={chain}&r=savipww&source=share_link",
            )
            self.assertNotIn("/buy", fomo_url(item))
            self.assertNotIn("/sell", fomo_url(item))

    def test_unknown_and_missing_chains_fall_back_to_the_invite_link(self):
        unknown_ids = (1, 143, 5042, None)
        for chain in unknown_ids:
            item = swap(
                side="sell",
                in_token=TOKEN,
                in_network_id=chain,
                network_id=None if chain is None else 1399811149,
            )
            self.assertEqual(fomo_url(item), OPEN_FOMO_URL)
        self.assertEqual(OPEN_FOMO_URL, "https://fomo.family/r/savipww")

    def test_profile_url_keeps_share_source_and_referral(self):
        from fomo_oneshot.links import profile_url
        url = profile_url("@PressingProfits")
        self.assertEqual(
            url,
            "https://fomo.family/profile/PressingProfits?source=share_link&r=savipww",
        )
        self.assertIn("r=savipww", url)
        self.assertNotIn("/coin", url)
        self.assertNotIn("chainId", OPEN_FOMO_URL)
        self.assertNotIn("/coin", OPEN_FOMO_URL)

    def test_side_specific_chain_is_not_replaced_by_the_other_leg(self):
        item = swap(
            side="sell",
            in_token=TOKEN,
            in_network_id=1,
            out_network_id=1399811149,
            network_id=1399811149,
        )
        self.assertEqual(fomo_url(item), OPEN_FOMO_URL)

        self.assertEqual(fomo_url(item), OPEN_FOMO_URL)

    def test_buy_links_the_received_token_and_sell_links_the_sent_token(self):
        bought = swap(
            side="buy",
            in_token="0x0000000000000000000000000000000000000001",
            out_token=TOKEN,
            in_network_id=8453,
            out_network_id=1399811149,
            network_id=8453,
        )
        sold = swap(
            side="sell",
            in_token=TOKEN,
            out_token="0x0000000000000000000000000000000000000001",
            in_network_id=1399811149,
            out_network_id=8453,
            network_id=8453,
        )
        self.assertIn("chainId=1399811149", fomo_url(bought))
        self.assertIn(f"address={TOKEN}", fomo_url(bought))
        self.assertNotIn("chainId=8453", fomo_url(bought))
        self.assertIn("chainId=1399811149", fomo_url(sold))
        self.assertNotIn("0x0000000000000000000000000000000000000001", fomo_url(sold))
        from fomo_oneshot.card import build_card
        text = build_card(handle="PressingProfits", swap=bought, fixture=False, replay=True).text
        self.assertIn("cross-chain in 8453 out 1399811149", text)
        self.assertIn("Solana 1399811149", text)
        self.assertIn("Not a live buy or sell signal. Not a recommendation.", text)

    def test_missing_leg_does_not_borrow_the_other_chain(self):
        item = swap(
            side="sell",
            in_token=TOKEN,
            in_network_id=None,
            out_network_id=8453,
            network_id=1399811149,
        )
        self.assertIsNone(item.token_network_id)
        self.assertEqual(fomo_url(item), OPEN_FOMO_URL)

    def test_bad_address_does_not_become_a_coin_url(self):
        item = swap(side="buy", out_token="not a token <script>", out_network_id=8453)
        self.assertEqual(fomo_url(item), OPEN_FOMO_URL)


if __name__ == "__main__":
    unittest.main()
