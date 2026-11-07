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

## Tests

```text
python3 -m unittest discover -s fomo_controls/tests -t .
python3 -m unittest discover -s fomo_oneshot/tests -t .
```

Python 3.11+ standard library only. No key and no network.
