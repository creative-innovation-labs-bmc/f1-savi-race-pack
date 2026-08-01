# Project brief

## Purpose

Create a reliable F1 SAVI League race-update pipeline. A single run should validate source data and prepare Flourish-ready CSVs, Microsoft Teams tables, race metadata and later media assets.

## Locked reference case

Round 11, Hungary, using the two CSV fixtures in `tests/fixtures/`.

## Critical data rule

The individual CSV contains race scores. The cumulative CSV contains the authoritative FantasyGP championship totals. They are related but not identical. Historical corrections exist, including a +13 adjustment for Snoopy at Race 07 and a -20 adjustment for We are the competition at Race 10.

The processor must therefore:

1. Validate both files together.
2. Preserve the cumulative totals exactly.
3. Record the difference between each race score and the change in cumulative total as an adjustment.
4. Stop on missing competitors, duplicate identities, malformed columns or mismatched headers.

## Current outputs

- Normalised individual and cumulative CSVs
- Race top 10 and overall top 10
- Podium tally with latest-round changes
- Podium-by-race table
- Biggest movers and drops
- Teams-ready HTML and plain text
- `race_data.json`
- QC report
- SHA-256 manifest

## Later phases

- Authenticated FantasyGP extraction for league `10527`
- Direct or live-data Flourish update
- Data-driven top-10 graphic
- Commentary briefing and script
- Script-aligned SRT and audiogram render
