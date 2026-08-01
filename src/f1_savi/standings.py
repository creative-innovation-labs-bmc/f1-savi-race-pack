from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from typing import Callable, Iterable, Sequence

from .dataset import calculate_adjustments, parse_round_header, validate_inputs
from .models import Competitor, Dataset, MovementEntry, PodiumTallyEntry, RacePackError, RankedEntry


def competition_rank(
    competitors: Iterable[Competitor], value_getter: Callable[[Competitor], int]
) -> list[RankedEntry]:
    sorted_competitors = sorted(
        competitors,
        key=lambda item: (-value_getter(item), item.team.casefold(), item.manager.casefold()),
    )
    ranked: list[RankedEntry] = []
    previous_points: int | None = None
    current_rank = 0
    for index, competitor in enumerate(sorted_competitors, start=1):
        points = value_getter(competitor)
        if points != previous_points:
            current_rank = index
            previous_points = points
        ranked.append(
            RankedEntry(current_rank, competitor.team, competitor.manager, points)
        )
    return ranked


def rank_column(dataset: Dataset, column_index: int) -> list[RankedEntry]:
    if column_index < 0 or column_index >= len(dataset.race_headers):
        raise RacePackError(f"Column index {column_index} is outside the race data.")
    return competition_rank(dataset.competitors, lambda item: item.values[column_index])


def top_by_rank(ranked: Sequence[RankedEntry], highest_rank: int = 10) -> list[RankedEntry]:
    return [entry for entry in ranked if entry.rank <= highest_rank]


def calculate_movements(cumulative: Dataset) -> tuple[list[MovementEntry], list[MovementEntry]]:
    if len(cumulative.race_headers) < 2:
        return [], []
    previous = rank_column(cumulative, len(cumulative.race_headers) - 2)
    current = rank_column(cumulative, len(cumulative.race_headers) - 1)
    previous_map = {(entry.team.casefold(), entry.manager.casefold()): entry.rank for entry in previous}

    movements: list[MovementEntry] = []
    for entry in current:
        previous_rank = previous_map[(entry.team.casefold(), entry.manager.casefold())]
        movements.append(
            MovementEntry(
                team=entry.team,
                manager=entry.manager,
                previous_rank=previous_rank,
                current_rank=entry.rank,
                movement=previous_rank - entry.rank,
                points=entry.points,
            )
        )

    movers = sorted(
        (item for item in movements if item.movement > 0),
        key=lambda item: (-item.movement, item.team.casefold(), item.manager.casefold()),
    )
    drops = sorted(
        (item for item in movements if item.movement < 0),
        key=lambda item: (item.movement, item.team.casefold(), item.manager.casefold()),
    )
    return movers, drops


def calculate_podiums(
    individual: Dataset,
) -> tuple[list[dict[str, object]], list[PodiumTallyEntry]]:
    current_counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    previous_counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    names: dict[tuple[str, str], tuple[str, str]] = {}
    podium_by_race: list[dict[str, object]] = []
    latest_index = len(individual.race_headers) - 1

    for column_index, header in enumerate(individual.race_headers):
        metadata = parse_round_header(header)
        ranked = rank_column(individual, column_index)
        podium: dict[int, list[dict[str, object]]] = {1: [], 2: [], 3: []}
        for entry in ranked:
            if entry.rank not in podium:
                continue
            key = (entry.team.casefold(), entry.manager.casefold())
            names[key] = (entry.team, entry.manager)
            podium[entry.rank].append(asdict(entry))
            current_counts[key][entry.rank - 1] += 1
            if column_index < latest_index:
                previous_counts[key][entry.rank - 1] += 1
        podium_by_race.append(
            {
                "header": metadata.header,
                "race": metadata.race,
                "round": metadata.round,
                "first": podium[1],
                "second": podium[2],
                "third": podium[3],
            }
        )

    tally: list[PodiumTallyEntry] = []
    for key, counts in current_counts.items():
        previous = previous_counts[key]
        team, manager = names[key]
        tally.append(
            PodiumTallyEntry(
                team=team,
                manager=manager,
                first=counts[0],
                first_change=counts[0] - previous[0],
                second=counts[1],
                second_change=counts[1] - previous[1],
                third=counts[2],
                third_change=counts[2] - previous[2],
                total=sum(counts),
                total_change=sum(counts) - sum(previous),
            )
        )

    tally.sort(
        key=lambda item: (
            -item.total,
            -item.first,
            -item.second,
            -item.third,
            item.team.casefold(),
            item.manager.casefold(),
        )
    )
    return podium_by_race, tally


def _serialise_dataclasses(items: Iterable[object]) -> list[dict[str, object]]:
    return [asdict(item) for item in items]


def build_payload(
    individual: Dataset,
    cumulative: Dataset,
    expected_competitors: int | None = 46,
    top_limit: int = 10,
) -> dict[str, object]:
    report = validate_inputs(individual, cumulative, expected_competitors)
    report.require_pass()

    latest = parse_round_header(individual.race_headers[-1])
    race_ranked = rank_column(individual, len(individual.race_headers) - 1)
    overall_ranked = rank_column(cumulative, len(cumulative.race_headers) - 1)
    race_top = top_by_rank(race_ranked, top_limit)
    overall_top = top_by_rank(overall_ranked, top_limit)
    movers, drops = calculate_movements(cumulative)
    podium_by_race, podium_tally = calculate_podiums(individual)
    adjustments = calculate_adjustments(individual, cumulative)
    latest_adjustments = [item for item in adjustments if item.round == latest.round and item.adjustment != 0]

    return {
        "metadata": asdict(latest),
        "competitor_count": len(individual.competitors),
        "race_top": _serialise_dataclasses(race_top),
        "overall_top": _serialise_dataclasses(overall_top),
        "podium_by_race": podium_by_race,
        "podium_tally": _serialise_dataclasses(podium_tally),
        "biggest_movers": _serialise_dataclasses(movers[:top_limit]),
        "biggest_drops": _serialise_dataclasses(drops[:top_limit]),
        "latest_adjustments": _serialise_dataclasses(latest_adjustments),
        "all_adjustments": _serialise_dataclasses([item for item in adjustments if item.adjustment != 0]),
        "qc": {
            "status": report.status,
            "errors": report.errors,
            "warnings": report.warnings,
            "checks": report.checks,
        },
    }
