from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .dataset import read_dataset, write_dataset
from .models import RacePackError
from .render import render_teams_html, render_teams_text, write_csv_table
from .standings import build_payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_race_pack(
    individual_path: str | Path,
    cumulative_path: str | Path,
    output_dir: str | Path,
    *,
    expected_competitors: int | None = 46,
    graph_url: str = "https://creative-innovation-labs-bmc.github.io/f1-savi-league/",
    flourish_races_id: int = 23536150,
    flourish_leaderboard_id: int = 23537908,
) -> dict[str, object]:
    individual = read_dataset(individual_path)
    cumulative = read_dataset(cumulative_path)
    payload = build_payload(individual, cumulative, expected_competitors)
    metadata = payload["metadata"]
    assert isinstance(metadata, dict)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    race_slug = re.sub(r"[^a-z0-9]+", "-", str(metadata["race"]).casefold()).strip("-")
    round_number = int(metadata["round"])
    individual_name = f"F1_Season2_Individual_R{round_number:02d}_{metadata['race']}.csv"
    cumulative_name = f"F1_Season2_Cumulative_R{round_number:02d}_{metadata['race']}_GRAPH_FIXED.csv"
    write_dataset(individual, output / individual_name)
    write_dataset(cumulative, output / cumulative_name)

    payload["flourish"] = {
        "races_visualisation_id": flourish_races_id,
        "leaderboard_visualisation_id": flourish_leaderboard_id,
        "races_edit_url": f"https://app.flourish.studio/visualisation/{flourish_races_id}/edit",
        "leaderboard_edit_url": f"https://app.flourish.studio/visualisation/{flourish_leaderboard_id}/edit",
    }
    payload["files"] = {
        "individual_csv": individual_name,
        "cumulative_csv": cumulative_name,
    }

    (output / "race_data.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output / "Teams_Update.txt").write_text(
        render_teams_text(payload, graph_url), encoding="utf-8"
    )
    (output / "Teams_Update.html").write_text(
        render_teams_html(payload, graph_url), encoding="utf-8"
    )

    write_csv_table(
        output / "race_top_10.csv",
        ["Pos", "Team", "Manager", "Pts"],
        [[item["rank"], item["team"], item["manager"], item["points"]] for item in payload["race_top"]],  # type: ignore[index]
    )
    write_csv_table(
        output / "overall_top_10.csv",
        ["Pos", "Team", "Manager", "Pts"],
        [[item["rank"], item["team"], item["manager"], item["points"]] for item in payload["overall_top"]],  # type: ignore[index]
    )
    write_csv_table(
        output / "latest_adjustments.csv",
        ["Race", "Round", "Team", "Manager", "Race points", "Cumulative delta", "Adjustment"],
        [[item["race"], item["round"], item["team"], item["manager"], item["race_points"], item["cumulative_delta"], item["adjustment"]] for item in payload["latest_adjustments"]],  # type: ignore[index]
    )

    qc = payload["qc"]
    assert isinstance(qc, dict)
    qc_markdown = [
        f"# QC report / Round {round_number:02d} / {metadata['race']}",
        "",
        f"**Status:** {str(qc['status']).upper()}",
        "",
        "## Checks",
        "",
    ]
    checks = qc["checks"]
    assert isinstance(checks, dict)
    qc_markdown.extend(f"- **{key.replace('_', ' ').title()}:** {value}" for key, value in checks.items())
    qc_markdown.extend(["", "## Warnings", ""])
    warnings = qc["warnings"]
    assert isinstance(warnings, list)
    qc_markdown.extend(f"- {warning}" for warning in warnings) if warnings else qc_markdown.append("- None")
    qc_markdown.extend(["", "## Hard errors", ""])
    errors = qc["errors"]
    assert isinstance(errors, list)
    qc_markdown.extend(f"- {error}" for error in errors) if errors else qc_markdown.append("- None")
    (output / "QC_REPORT.md").write_text("\n".join(qc_markdown) + "\n", encoding="utf-8")

    manifest_files = sorted(path for path in output.iterdir() if path.is_file() and path.name != "manifest.json")
    manifest = {
        "round": round_number,
        "race": metadata["race"],
        "slug": race_slug,
        "files": {path.name: _sha256(path) for path in manifest_files},
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return payload


def verify_manifest(output_dir: str | Path) -> dict[str, object]:
    output = Path(output_dir)
    manifest_path = output / "manifest.json"
    if not manifest_path.exists():
        raise RacePackError(f"Manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for name, expected_hash in manifest.get("files", {}).items():
        path = output / name
        if not path.exists():
            failures.append(f"Missing file: {name}")
            continue
        actual = _sha256(path)
        if actual != expected_hash:
            failures.append(f"Hash mismatch for {name}: expected {expected_hash}, found {actual}")
    if failures:
        raise RacePackError("; ".join(failures))
    return manifest
