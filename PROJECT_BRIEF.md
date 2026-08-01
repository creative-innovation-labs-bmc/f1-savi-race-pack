# Project brief

## Description

Automated race-pack generator for the F1 SAVI League, producing Flourish-ready CSVs, validated standings, Teams-ready tables, commentary data and future media assets.

## Build brief

Purpose:
Create one reliable workflow for each F1 SAVI League race update. Use the uploaded Hungary Round 11 individual and cumulative CSVs as the locked reference case.

Users:
Fooch as the league administrator, with outputs prepared for Microsoft Teams, Flourish and later branded media production.

Phase 1 features:
- Read a canonical individual race-points CSV.
- Generate the cumulative CSV rather than maintaining it separately.
- Validate headers, participant count, duplicate teams/managers, numeric scores and cumulative arithmetic.
- Calculate competition ranks with proper tied-position handling.
- Generate race top 10 and overall top 10.
- Generate podium tally with per-race and total changes.
- Generate podium-by-race table.
- Generate biggest movers and biggest drops since the previous round.
- Generate Teams-ready HTML with copy buttons plus a plain-text fallback.
- Generate a machine-readable race_data.json for later graphic and commentary automation.
- Preserve manager handles and support a configurable real-name mapping.
- Include automated tests that reproduce and verify Hungary Round 11.
- Include a GitHub Actions quality-control workflow.

Phase 2:
- Authenticated Playwright extraction from FantasyGP league 10527.
- Keep credentials only in GitHub Actions Secrets.
- Fail safely if participant count or totals do not validate.
- Keep the last valid output on extraction failure.

Phase 3:
- Data-driven 1024 x 1536 top-10 graphic renderer.
- Commentary briefing and script support.
- Known-script audio alignment to corrected SRT.
- Branded 1080 x 1080 audiogram renderer.

External references:
- FantasyGP league: https://fantasygp.com/league/?lid=10527
- Flourish races: https://public.flourish.studio/visualisation/23536150/
- Flourish leaderboard: https://public.flourish.studio/visualisation/23537908/
- Existing interactive graphs: https://creative-innovation-labs-bmc.github.io/f1-savi-league/

Constraints:
- Australian English.
- No credentials committed to the repository.
- Deterministic calculations and renders.
- Every stage must have explicit QC checks and failure reporting.
- Do not overwrite valid outputs when validation fails.
- Treat 46 competitors as the current expected field size, configurable for future seasons.
