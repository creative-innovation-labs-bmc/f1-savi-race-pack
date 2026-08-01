# F1 SAVI Race Pack

A validated race-update generator for the F1 SAVI League.

It authenticates to FantasyGP, reads league `10527`, validates all 46 competitors and produces a consistent package for Flourish, Microsoft Teams and future graphic/audio automation.

## Data rules

FantasyGP can apply corrections that do not appear in the individual race-point history. The cumulative standings therefore cannot be safely recreated by simply adding the individual columns.

This project treats:

- **Individual CSV** as the source for race results, podiums and race history
- **Cumulative CSV** as the source for championship position, totals and movement

Every mismatch is recorded as an adjustment instead of silently changing the data.

The canonical Season 2 masters are stored in:

```text
data/season2/individual.csv
data/season2/cumulative.csv
```

## Race update workflow

After FantasyGP publishes a race result:

1. Open the repository in GitHub.
2. Select **Actions**.
3. Select **FantasyGP race update**.
4. Choose **Run workflow**.
5. Select `preview` first.
6. Wait for the workflow to finish successfully.
7. Download the `f1-savi-validated-race-pack` artifact.
8. Review `update-summary.json`, `QC_REPORT.md` and `Teams_Update.html`.
9. Run the workflow again with `apply` after the preview is correct.

`preview` never changes the repository. `apply` commits the validated individual and cumulative master CSVs only when FantasyGP reports the next completed round.

The workflow stops without writing data when:

- authentication fails
- FantasyGP returns fewer or more than 46 competitors
- race and overall competitor lists differ
- managers are duplicated, missing or unexpected
- a round has been skipped
- an existing round’s points no longer match FantasyGP
- the generated Race Pack fails its manifest check

FantasyGP credentials are read only from the encrypted repository secrets `FANTASYGP_USERNAME` and `FANTASYGP_PASSWORD`.

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
- authenticated FantasyGP snapshot and update summary

Open `Teams_Update.html`, then use **Copy complete Teams update**.

## Manual CSV workflow

The original Phase 1 workflow remains available when a manual source file is needed:

1. Add the individual and cumulative CSVs to the repository.
2. Open **Actions**.
3. Select **Build race pack**.
4. Enter the two repository file paths.
5. Download the `f1-savi-race-pack` artifact.

## Run locally

Requires Python 3.11 or newer. Phase 1 uses only the Python standard library. Live FantasyGP extraction additionally requires Playwright and Chromium.

### Windows PowerShell

```powershell
$env:PYTHONPATH = "src"
python -m f1_savi build `
  --individual data/season2/individual.csv `
  --cumulative data/season2/cumulative.csv `
  --output build/current
python -m f1_savi verify --output build/current
```

### macOS or Linux

```bash
PYTHONPATH=src python -m f1_savi build \
  --individual data/season2/individual.csv \
  --cumulative data/season2/cumulative.csv \
  --output build/current
PYTHONPATH=src python -m f1_savi verify --output build/current
```

## Quality control

Windows PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m compileall -q src scripts tests
python -m unittest discover -s tests -v
```

macOS or Linux:

```bash
python -m compileall -q src scripts tests
PYTHONPATH=src python -m unittest discover -s tests -v
```

The suite locks ranking ties, Hungary reference outputs, podium changes, movement calculations, cumulative corrections, FantasyGP pagination, competitor reconciliation, label cleanup and manifest integrity.

Pull requests run both deterministic QC and a read-only authenticated FantasyGP preview. Neither check can update the season masters.

## Current Flourish projects

- Races: visualisation `23536150`
- Leaderboard: visualisation `23537908`

The generated CSVs preserve their current column structure. Publishing remains a separate step until a supported Flourish live-data or publishing route is configured.

## Roadmap

1. Phase 1: validated race-pack generator
2. Phase 2: authenticated FantasyGP league extraction and safe master update
3. Phase 3: automated top-10 graphic, commentary data, SRT alignment and audiogram rendering
