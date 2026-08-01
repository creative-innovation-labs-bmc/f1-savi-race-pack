from __future__ import annotations

import csv
import re
from pathlib import Path

from .models import AdjustmentEntry, Competitor, Dataset, IDENTITY_HEADER, ROUND_HEADER_RE, RacePackError, RoundMetadata, ValidationReport


def parse_round_header(header: str) -> RoundMetadata:
    match = ROUND_HEADER_RE.fullmatch(header.strip())
    if not match:
        raise RacePackError(
            f"Race column {header!r} does not follow '<Race> - Race NN'."
        )
    return RoundMetadata(
        header=header.strip(),
        race=match.group("race").strip(),
        round=int(match.group("round")),
    )


def parse_identity(value: str) -> tuple[str, str]:
    if "|" not in value:
        raise RacePackError(f"Identity {value!r} is missing the '|' separator.")
    team, manager = (part.strip() for part in value.rsplit("|", 1))
    if not team or not manager:
        raise RacePackError(f"Identity {value!r} must include a team and manager.")
    return team, manager


def read_dataset(path: str | Path) -> Dataset:
    source_path = Path(path)
    if not source_path.exists():
        raise RacePackError(f"Input file does not exist: {source_path}")

    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    if not rows:
        raise RacePackError(f"Input file is empty: {source_path}")
    headers = tuple(cell.strip() for cell in rows[0])
    if len(headers) < 2 or headers[0] != IDENTITY_HEADER:
        raise RacePackError(
            f"First column must be {IDENTITY_HEADER!r}; found {headers[0] if headers else None!r}."
        )

    metadata = [parse_round_header(header) for header in headers[1:]]
    expected_rounds = list(range(1, len(metadata) + 1))
    actual_rounds = [item.round for item in metadata]
    if actual_rounds != expected_rounds:
        raise RacePackError(
            f"Race columns must be sequential from Race 01; found {actual_rounds}."
        )

    competitors: list[Competitor] = []
    keys: set[tuple[str, str]] = set()
    for row_number, row in enumerate(rows[1:], start=2):
        if len(row) != len(headers):
            raise RacePackError(
                f"Row {row_number} has {len(row)} columns; expected {len(headers)}."
            )
        team, manager = parse_identity(row[0])
        key = (team.casefold(), manager.casefold())
        if key in keys:
            raise RacePackError(f"Duplicate competitor at row {row_number}: {team} | {manager}")
        keys.add(key)

        values: list[int] = []
        for column_number, raw in enumerate(row[1:], start=2):
            text = raw.strip()
            if not re.fullmatch(r"-?\d+", text):
                raise RacePackError(
                    f"Row {row_number}, column {column_number} is not an integer: {raw!r}."
                )
            values.append(int(text))
        competitors.append(Competitor(team, manager, tuple(values)))

    return Dataset(headers, tuple(competitors), str(source_path))


def write_dataset(dataset: Dataset, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(dataset.headers)
        for competitor in dataset.competitors:
            writer.writerow([competitor.identity, *competitor.values])


def _key_map(dataset: Dataset) -> dict[tuple[str, str], Competitor]:
    return {competitor.key: competitor for competitor in dataset.competitors}


def calculate_adjustments(
    individual: Dataset, cumulative: Dataset
) -> list[AdjustmentEntry]:
    individual_map = _key_map(individual)
    cumulative_map = _key_map(cumulative)
    adjustments: list[AdjustmentEntry] = []
    for key, race_competitor in individual_map.items():
        cumulative_competitor = cumulative_map[key]
        for index, header in enumerate(individual.race_headers):
            metadata = parse_round_header(header)
            previous_total = cumulative_competitor.values[index - 1] if index else 0
            cumulative_delta = cumulative_competitor.values[index] - previous_total
            race_points = race_competitor.values[index]
            adjustments.append(
                AdjustmentEntry(
                    race=metadata.race,
                    round=metadata.round,
                    team=race_competitor.team,
                    manager=race_competitor.manager,
                    race_points=race_points,
                    cumulative_delta=cumulative_delta,
                    adjustment=cumulative_delta - race_points,
                )
            )
    return sorted(
        adjustments,
        key=lambda item: (item.round, item.team.casefold(), item.manager.casefold()),
    )


def validate_inputs(
    individual: Dataset,
    cumulative: Dataset,
    expected_competitors: int | None = 46,
) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, object] = {}

    checks["individual_rows"] = len(individual.competitors)
    checks["cumulative_rows"] = len(cumulative.competitors)
    checks["race_columns"] = len(individual.race_headers)

    if individual.headers != cumulative.headers:
        errors.append("Individual and cumulative CSV headers do not match exactly.")

    if expected_competitors is not None:
        if len(individual.competitors) != expected_competitors:
            errors.append(
                f"Individual CSV contains {len(individual.competitors)} competitors; expected {expected_competitors}."
            )
        if len(cumulative.competitors) != expected_competitors:
            errors.append(
                f"Cumulative CSV contains {len(cumulative.competitors)} competitors; expected {expected_competitors}."
            )

    individual_keys = set(_key_map(individual))
    cumulative_keys = set(_key_map(cumulative))
    if individual_keys != cumulative_keys:
        missing_from_cumulative = sorted(individual_keys - cumulative_keys)
        missing_from_individual = sorted(cumulative_keys - individual_keys)
        errors.append(
            "Competitor identities differ between files. "
            f"Missing from cumulative: {missing_from_cumulative}; "
            f"missing from individual: {missing_from_individual}."
        )

    if individual.headers:
        latest = parse_round_header(individual.headers[-1])
        checks["latest_round"] = latest.round
        checks["latest_race"] = latest.race

    if not errors:
        adjustments = calculate_adjustments(individual, cumulative)
        non_zero = [item for item in adjustments if item.adjustment != 0]
        checks["non_zero_adjustments"] = len(non_zero)
        checks["latest_round_adjustments"] = sum(
            1 for item in non_zero if item.round == len(individual.race_headers)
        )
        if non_zero:
            warnings.append(
                f"Detected {len(non_zero)} cumulative corrections across the season. "
                "The cumulative CSV is treated as authoritative rather than recalculated from race points."
            )

    return ValidationReport(errors, warnings, checks)
