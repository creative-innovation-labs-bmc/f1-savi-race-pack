# F1 SAVI Race Pack

A validated race-update generator for the F1 SAVI League.

It converts the individual race-points CSV and the authoritative cumulative standings CSV into a consistent package for Flourish, Microsoft Teams and future graphic/audio automation.

## Why two source files remain necessary

FantasyGP can apply corrections that do not appear in the individual race-point history. The cumulative standings therefore cannot be safely recreated by simply adding the individual columns.

This project treats:

- **Individual CSV** as the source for race results, podiums and race history
- **Cumulative CSV** as the source for championship position, totals and movement

Every mismatch is recorded as an adjustment instead of silently changing the data.

## Quick start

Requires Python 3.11 or newer.

```bash
python -m pip install --no-build-isolation -e .
python -m f1_savi build \
  --individual tests/fixtures/F1_Season2_Individual_R11_Hungary.csv \
  --cumulative tests/fixtures/F1_Season2_Cumulative_R11_Hungary_GRAPH_FIXED.csv \
  --output build/round-11-hungary
python -m f1_savi verify --output build/round-11-hungary
```

Open `build/round-11-hungary/Teams_Update.html`, then use **Copy complete Teams update**.

## Output package

- Flourish-ready individual and cumulative CSVs
- `race_top_10.csv`
- `overall_top_10.csv`
- `Teams_Update.html`
- `Teams_Update.txt`
- `race_data.json`
- `latest_adjustments.csv`
- `QC_REPORT.md`
- `manifest.json`

## Quality control

```bash
python -m unittest discover -s tests -v
```

The test suite locks the Hungary Round 11 rankings, tie behaviour, podium changes, movement calculations, known FantasyGP corrections and output hashes.

GitHub Actions runs the same tests on every pull request and builds the Hungary reference pack as an artifact.

## Current Flourish projects

- Races: visualisation `23536150`
- Leaderboard: visualisation `23537908`

The generated CSVs preserve their current column structure. Publishing remains a separate step until a supported Flourish live-data or API route is configured.

## Roadmap

1. Phase 1: validated race-pack generator
2. Phase 2: authenticated FantasyGP league extraction
3. Phase 3: automated top-10 graphic, commentary data, SRT alignment and audiogram rendering
