# One-shot FOMO activity card

Isolated dry-run test: read one page of a fomo.family trader's swaps from the public pumpfomo data API and render one historical Telegram card. It does not trade, poll, or message anyone unless `--send` is set.

This is not wired up. Nothing here starts a scheduler, edits the published desk, or sends a message.

## Gap

This repository is the static Plan B desk site (`index.html`, `app.js`, and the published `d/` snapshot). It does not contain the deployed `/workspace/desk` runtime, `links.py`, or a Telegram notifier. Those sources are not versioned here, so this package does not import them and does not invent their config.

What the published snapshot does show, and what this package follows:

- Coin links: `https://fomo.family/coin?address=...&chainId=1399811149&r=savipww`
- Profile links already include `source=share_link` (`fomo_profile` in `state.json`)
- Invite / unknown-chain fallback: `https://fomo.family/r/savipww`
- Owner chat `8578901453` (`desk.owner_chat_id`)
- Paper balance `201.25` and scanner min liquidity `40000` are unchanged because this package never reads or writes that snapshot

`source=share_link` is added to coin links because that share parameter is required and is already used on the profile URL in the same snapshot. The coin path, `address`, `chainId`, and `r=savipww` match the published coin links. Unknown chain ids do not get a made-up coin route.

## Provider

pumpfomo is an unofficial read-only data API. It is not the FOMO official API and it is not a FOMO session.

Documented routes used here:

- `GET /v1/fomo/users/{handle}/positions` — one page of swaps (`data.swaps`, `data.hasNextPage`). Docs: https://pumpfomo.com/docs/fomo-user-positions
- `GET /v1/fomo/users/{handle}/following` — optional, `data.users[].userHandle` only. Docs: https://pumpfomo.com/docs/fomo-user-following
- Profile route is documented at https://pumpfomo.com/docs/fomo-user and is not called

The key, when a later local run needs one, comes from the environment variable `PUMPFOMO_API_KEY`. The bot token comes from `TELEGRAM_BOT_TOKEN`. Neither is read from a file, logged, or put in a URL query.

## Behavior

One invocation does at most 3 HTTP calls, and a normal run does 1 (positions) or 2 (positions + `--following`). There is no cursor, no pagination loop, no retry, and no redirect follow. `hasNextPage` is reported and then ignored. At most 50 rows from that one page are kept.

Default handle is `PressingProfits`. `--following` lists who that handle follows. It does not fetch each follow.

The first successful read seeds every returned swap id into a separate JSON file (`--seen`, default `.fomo_oneshot/seen.json`, gitignored). That first read sends nothing, including when `--send` is set, so historical rows do not flood the chat. A later invocation may preview the single newest id that was not already seen. Other new ids stay unseen and are not sent. `--replay` is the explicit sample: it renders the newest id on the page as a TEST / HISTORICAL card and does not clear the seen file.

`--send` is required before any Telegram call. The only accepted chat is `8578901453`. There is no recipient flag. The message is one HTML card plus one `Open FOMO` URL button. The button opens the coin link or the invite link. It does not call a buy or sell endpoint.

`401`, `403`, `402`, and `429` stop the invocation. `402` does not upgrade or top up. Other HTTP errors also stop after that single attempt. Response bodies are not copied into the report. Bearer keys, `pf_live_` values, and Telegram bot URLs are redacted if they ever reach a string that is printed.

Side comes only from `display.side` (`buy` or `sell`). In is the token the trader sent and out is the token received. A missing or unknown side stays unknown. Chain names are Solana `1399811149`, Robinhood `4663`, Base `8453`, and BNB `56`. Any other id, including a missing id, uses the invite link. Missing numbers stay unknown. Market cap, liquidity, holders, and PnL are not invented. The swap `address` field is not treated as a handle or as the coin.

## Offline example

This fixture is not a live capture and not data verification. The amounts, price, token, chain, provider, and `createdAt` match the parent-verified PressingProfits sell. The swap id was not provided (`fixture-sell-1` is a label). The out-token address was not provided, so it is null. The parent described the received asset as USDC; this card does not print that ticker because the payload has no symbol field.

```text
python3 -m fomo_oneshot --fixture fomo_oneshot/fixtures/sell_page.json --replay --seen /tmp/fomo-oneshot-seen.json
```

```text
mode: dry-run
replay: yes
fixture: yes
handle: PressingProfits
requests: 0
request_cap: 3
sends: 0
first_run: yes
seen_ids: 1
candidate: fixture-sell-1
deferred_unseen: 0
has_next_page: no
truncated: no
skipped_malformed: 0
stopped: no
seen: /tmp/fomo-oneshot-seen.json
button: Open FOMO https://fomo.family/coin?address=BtSvtGREKtTWuc5YMQE1SVHJsGCb5YCyFS8G73sypump&chainId=1399811149&r=savipww&source=share_link
card:
TEST / HISTORICAL
FIXTURE — not a live capture and not data verification.
Historical replay of one fetched swap.
Not a live buy or sell signal. Not a recommendation.

@PressingProfits
sell
sold 20973102.33
received 186.206
token BtSvtGREKtTWuc5YMQE1SVHJsGCb5YCyFS8G73sypump
USD 186.21
price 0.00000898841
Solana 1399811149
provider DFLOW
source time 2026-11-07T01:46:05Z
Nov 6 21:46:05 AST
```

`2026-11-07T01:46:05Z` is `Nov 6 21:46:05 AST` (fixed UTC-4).

Run from the directory that contains the `fomo_oneshot` package (`python3 -m fomo_oneshot ...`). This package is not the deployed desk.

## Later commands

Run these only after review, from a checkout of this branch. Do not run them inside the deployed desk tree, and do not point `--seen` at `d/` or at a desk database. Put the key and bot token in the environment. Do not put them in the command line or in a file in this repo.

Offline, no key, no Telegram, no credits:

```text
python3 -m fomo_oneshot --fixture fomo_oneshot/fixtures/sell_page.json --replay --seen /tmp/fomo-oneshot-seen.json
```

Live dry-run. One positions call, 2 credits, zero Telegram messages. The first run only seeds seen ids.

```text
python3 -m fomo_oneshot --handle PressingProfits --seen /tmp/fomo-oneshot-seen.json
```

Optional following lookup for the same handle. One extra call, 2 more credits. It does not fetch positions for each follow.

```text
python3 -m fomo_oneshot --handle CivilNewCanid --following --seen /tmp/fomo-oneshot-seen.json
```

Labeled historical sample, still zero sends:

```text
python3 -m fomo_oneshot --handle PressingProfits --replay --seen /tmp/fomo-oneshot-seen.json
```

Explicit owner-only send, max one card, only when a local test send is wanted. Requires `PUMPFOMO_API_KEY` and `TELEGRAM_BOT_TOKEN`.

```text
python3 -m fomo_oneshot --handle PressingProfits --replay --send --seen /tmp/fomo-oneshot-seen.json
```

## Tests

```text
python3 -m unittest discover -s fomo_oneshot/tests -t .
```

Dependencies: Python 3.11+ standard library only. No pip install. The tests use fixtures and injected HTTP transports. They do not call pumpfomo or Telegram.

## Limitations

- Not deployed, not scheduled, and not started with the desk.
- Does not change paper balance, positions, signals, or scanner settings.
- One page per invocation. Older swaps behind `hasNextPage` are not read. A page longer than 50 rows is truncated locally.
- Swaps without a usable id are not stored and are not alerted.
- A fresh seen file plus `--send` still sends nothing. Use `--replay` to show the newest historical swap, and `--replay --send` to deliver that one sample.
- No symbol, market cap, liquidity, holders, or PnL fields are filled in.
- Wallet `address` on a swap is not mapped to a handle.
- Chains outside Solana, Robinhood, Base, and BNB use the invite link.
- `503` is not retried, even though the provider docs say a short retry is free.
- Env `https_proxy` is ignored, so the bearer token is not sent to a proxy and a proxy hop cannot add a request outside the cap.
- A cross-chain swap links only the coin leg: the received token on a buy, the sent token on a sell. If that leg's chain id is missing and the other leg names a different chain, the button is the invite link. Both leg ids are printed when they differ.
- Provider and Telegram failures are reduced to a status line. The urllib error, request, response body, and exception chain are not kept.
- The seen file is local JSON, not the desk database. A corrupt seen file stops the run instead of being treated as empty.
- Fixture files under `fomo_oneshot/fixtures/` are labeled fixtures. They are not stored API responses.

Account menus and filter settings live in `fomo_controls/`. They are inactive and do not poll. A Telegram send counts only when the response has `ok: true` and a positive integer `message_id`. A malformed response is unconfirmed and is not retried.
