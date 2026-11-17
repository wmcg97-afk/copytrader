# Inactive FOMO account controls

Owner-only Telegram menus for accounts and filters. This package does not poll, does not call pumpfomo, and does not send Telegram messages. It turns one injected update into a description of the menu to edit.

The desk bot `@wyatt_desk_bot` may already consume updates in `/workspace/desk`. That runtime is not in this repo. Do not run a second `getUpdates` loop or webhook for the same bot. A later integration, if the desk consumer is the only reader, can pass an update into `fomo_controls.apply` and edit the same message. That wiring is not done here.

## Implemented

- Fixed owner `8578901453` for both the chat and the sender, on messages and callbacks. Anyone else is ignored and the stored menu does not change.
- Accounts: add one or many handles, search, pages of 10, profile links, delete one and delete all after confirm.
- The four handles PressingProfits, bystevenr, escobarpablo, and savipww start on the list with source `verified-follows-2026-11-07`. That is the previously verified follow list, not a fresh import.
- Filters: minimum trade, market cap, liquidity, holders, the four networks, sells, silent, emoji, and a requested interval. EN and RU labels.
- Missing market cap, liquidity, and holder counts are unknown. An enabled threshold rejects the swap instead of letting it through.
- Pause and resume are stored preferences. Resume does not start polling or a collector. The guide's 20s value is only a requested interval. No monitoring budget is approved, so it never becomes a cadence.
- Seen ids are recorded only by `seed_snapshot` from an injected positions payload. Adding a handle or editing a filter does not read the provider and does not send a backlog.
- Menus edit the same message after the first `/start`.
- Profile links are `https://fomo.family/profile/{handle}?source=share_link&r=savipww`. Unknown coin chains use `https://fomo.family/r/savipww`.

State is a separate JSON file, default `.fomo_controls/controls.json`. It is refused inside the published `d/` tree and refused if the filename is `state.json`, `activity.json`, or `chart.json`.

## Unavailable

- Import top 30. The leaderboard response schema was not verified, so the button explains that and makes no request.
- Breaking detection. The 3-traders / 30-minute values are stored only. No breaking card is produced.
- A running collector, `getUpdates`, webhooks, and the 20s loop.
- Provider market cap, liquidity, and holder fields. They are not in the swaps payload.

Monitoring is not running, and this package does not attach itself to a running bot.

## Desk hook

The deployed desk already has the only `getUpdates` loop in `telegram.py`. `/fomo` is handled inside that loop. `/start`, status, pause, buy, sell, and the `bought:` / `sold:` buttons stay on the desk path. Free text is given to the menu only after Add, Search, or a filter prompt, and a desk command still wins.

Install from a checkout or from the release archive. It checks the hash of `telegram.py`, backs that file up, and copies these packages. It does not restart the process, send a message, or write `settings.json`, `secrets/`, `data/`, or `web/`.

```text
python3 -m fomo_controls.install_desk --desk /workspace/desk
python3 -m fomo_controls.install_desk --desk /workspace/desk --apply
```

Restart the existing desk process yourself after `--apply`. Do not start a second Python process. Then, from the owner chat, send `/fomo`. The menu says monitoring is inactive. Resume does not start trader polling.

An upgrade from the already patched `telegram.py` (`d89cfdc5dacb476c0a598f969179c9a158580833f58490a99afa7414b2a51c4e`) copies these packages and does not rewrite that file. It also does not touch `.fomo_controls/`, `settings.json`, `secrets/`, `data/`, or `web/`. Package directories that already exist are copied to `fomo_controls.bak-d89cfdc5dacb` and `fomo_oneshot.bak-d89cfdc5dacb` before their files are updated. Rollback is those backups plus `telegram.py.bak-fa512ba0f95c` if the hook itself was installed in the earlier step.

## Market data

`fomo_controls.dex.process_candidate` is the only path that calls DEX Screener. The menu, `/fomo`, and the one-shot historical send do not call it. There is no background refresh. Solana only: `GET https://api.dexscreener.com/token-pairs/v1/solana/{token}`. The coin is the token received on a buy and the token sent on a sell. The pool must have that exact base address. Liquidity is the one winning pool, not a sum. FDV is never treated as market cap. Results are cached at least 30 seconds and are stale after 60 seconds. The fetched time is the HTTP observation, not the swap time and not a chain update time.

A candidate evaluation has to be requested by a future collector. Until that exists, enabled market-cap and liquidity thresholds still reject unenriched swaps. The saved public sample, market cap 3593 and liquidity 3348.53, fails the default $50,000 and $20,000 thresholds. Zero is a real zero. Missing or invalid numbers are unknown and cannot pass.

## Tests

```text
python3 -m unittest discover -s fomo_controls/tests -t .
python3 -m unittest discover -s fomo_oneshot/tests -t .
```

Python 3.11+ standard library only. No key and no network.
