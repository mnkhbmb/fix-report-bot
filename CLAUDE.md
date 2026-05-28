# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Bot

```bash
python -m pip install -r requirements.txt
python bot.py
```

Required `.env` variables:
```
DISCORD_TOKEN=...
GOOGLE_SHEET_ID=...
GOOGLE_CREDS_FILE=credentials.json   # defaults to credentials.json
REPAIR_CHANNEL_NAME=repairs          # defaults to "repairs"
```

`credentials.json` must be a Google Service Account key with Editor access to the target Sheet.

## Architecture

Two-file structure: `bot.py` handles Discord slash commands and `sheets.py` manages all Google Sheets I/O.

**`bot.py`** — `RepairBot(discord.Client)` holds a `SheetsClient` instance and registers four slash commands: `/shipment`, `/received`, `/fix`, `/status`. All commands are restricted to a single channel (`REPAIR_CHANNEL_NAME`). Commands defer the response immediately (since Sheets API calls are slow) then use `followup.send`.

**`sheets.py`** — `SheetsClient` wraps the Google Sheets v4 API. On init it auto-creates the three tabs (`Repairs`, `Fixed`, `Shipments`) if missing and ensures headers are in place. All reads go through `_get_rows(tab)` which fetches the entire tab as a list of lists. Row numbers are 1-based (matching the Sheets API).

**Data flow for `/fix`:** The completed REP row is appended to the `Fixed` tab, then the original row is deleted from `Repairs` using `batchUpdate` (requires a sheet `sheetId`, not the tab name). If no REP rows remain for that SHP, the shipment status is set to `Дууссан` (Done).

**ID generation** (`_next_id`): Scans existing rows for the highest numeric suffix and increments by 1, zero-padded to 4 digits (e.g. `REP-0007`). For REP IDs, both `Repairs` and `Fixed` tabs are scanned to avoid collisions.

## Google Sheet Schema

| Tab | Key columns |
|-----|-------------|
| `Repairs` | REP ID, SHP ID, Branch, Item, Qty, Reporter, Date, Status |
| `Fixed` | REP ID, SHP ID, Branch, Item, Qty, Reporter, Rep-Date, Fixer, Fix-Date, Notes |
| `Shipments` | SHP ID, Branch, Reporter, Date, Status, Receiver, Received-Date, Notes |

Column indices are defined as module-level constants (`R_ID`, `S_STATUS`, etc.) — use these rather than raw integers when editing `sheets.py`.
