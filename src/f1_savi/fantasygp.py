from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .dataset import parse_round_header, read_dataset, write_dataset
from .models import Competitor, Dataset, RacePackError


@dataclass(frozen=True)
class FantasyGPRow:
    team: str
    manager: str
    points: int
    position: int
    ranking: int
    position_change: int
    team_uid: str = ""
    profile_link: str = ""

    @property
    def manager_key(self) -> str:
        return self.manager.casefold().strip()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def parse_integer(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise RacePackError(f"FantasyGP field {field!r} is boolean rather than numeric.")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip().replace(",", "")
    match = re.fullmatch(r"-?\d+", text)
    if not match:
        raise RacePackError(f"FantasyGP field {field!r} is not an integer: {value!r}")
    return int(text)


def _array(response: dict[str, Any], key: str, howmany: int) -> list[Any]:
    value = response.get(key)
    if not isinstance(value, list):
        raise RacePackError(f"FantasyGP response is missing array {key!r}.")
    if len(value) < howmany:
        raise RacePackError(
            f"FantasyGP response array {key!r} has {len(value)} values; expected at least {howmany}."
        )
    return value


def rows_from_league_response(response: dict[str, Any]) -> list[FantasyGPRow]:
    howmany = parse_integer(response.get("howmany", 0), field="howmany")
    if howmany < 0 or howmany > 500:
        raise RacePackError(f"FantasyGP returned an invalid page size: {howmany}.")
    if howmany == 0:
        return []

    teams = _array(response, "teamnames", howmany)
    managers = _array(response, "teamdisplay_names", howmany)
    points = _array(response, "teampoints", howmany)
    positions = _array(response, "teampos", howmany)
    rankings = _array(response, "teamrankings", howmany)
    changes = _array(response, "teamposchange", howmany)
    team_uids = response.get("teamuids") if isinstance(response.get("teamuids"), list) else [""] * howmany
    profiles = response.get("profilelinks") if isinstance(response.get("profilelinks"), list) else [""] * howmany

    rows: list[FantasyGPRow] = []
    for index in range(howmany):
        team = str(teams[index]).strip()
        manager = str(managers[index]).strip()
        if not team or not manager:
            raise RacePackError(f"FantasyGP returned a blank team or manager at page row {index + 1}.")
        rows.append(
            FantasyGPRow(
                team=team,
                manager=manager,
                points=parse_integer(points[index], field=f"teampoints[{index}]"),
                position=parse_integer(positions[index], field=f"teampos[{index}]"),
                ranking=parse_integer(rankings[index], field=f"teamrankings[{index}]"),
                position_change=parse_integer(changes[index], field=f"teamposchange[{index}]"),
                team_uid=str(team_uids[index]).strip() if index < len(team_uids) else "",
                profile_link=str(profiles[index]).strip() if index < len(profiles) else "",
            )
        )
    return rows


def combine_league_pages(
    pages: Iterable[dict[str, Any]], *, expected_competitors: int | None = 46
) -> tuple[FantasyGPRow, ...]:
    rows: list[FantasyGPRow] = []
    declared_totals: set[int] = set()
    for page in pages:
        if "total" in page:
            declared_totals.add(parse_integer(page["total"], field="total"))
        rows.extend(rows_from_league_response(page))

    if len(declared_totals) > 1:
        raise RacePackError(f"FantasyGP pagination returned inconsistent totals: {sorted(declared_totals)}")
    if declared_totals and len(rows) != next(iter(declared_totals)):
        raise RacePackError(
            f"FantasyGP pagination returned {len(rows)} rows but declared {next(iter(declared_totals))}."
        )
    if expected_competitors is not None and len(rows) != expected_competitors:
        raise RacePackError(
            f"FantasyGP returned {len(rows)} competitors; expected {expected_competitors}."
        )

    seen: set[str] = set()
    duplicates: list[str] = []
    for row in rows:
        if row.manager_key in seen:
            duplicates.append(row.manager)
        seen.add(row.manager_key)
    if duplicates:
        raise RacePackError(f"FantasyGP returned duplicate managers: {sorted(set(duplicates))}")

    return tuple(rows)


def _manager_map(dataset: Dataset) -> dict[str, Competitor]:
    result: dict[str, Competitor] = {}
    duplicates: list[str] = []
    for competitor in dataset.competitors:
        key = competitor.manager.casefold().strip()
        if key in result:
            duplicates.append(competitor.manager)
        result[key] = competitor
    if duplicates:
        raise RacePackError(f"Source CSV contains duplicate managers: {sorted(set(duplicates))}")
    return result


def _row_map(rows: Iterable[FantasyGPRow]) -> dict[str, FantasyGPRow]:
    return {row.manager_key: row for row in rows}


def update_season_datasets(
    individual_path: str | Path,
    cumulative_path: str | Path,
    *,
    race_name: str,
    round_number: int,
    race_rows: Iterable[FantasyGPRow],
    standings_rows: Iterable[FantasyGPRow],
    output_individual_path: str | Path,
    output_cumulative_path: str | Path,
    expected_competitors: int | None = 46,
) -> dict[str, object]:
    individual = read_dataset(individual_path)
    cumulative = read_dataset(cumulative_path)
    if individual.headers != cumulative.headers:
        raise RacePackError("Source individual and cumulative CSV headers do not match.")

    base_latest = parse_round_header(individual.race_headers[-1])
    if round_number < base_latest.round:
        raise RacePackError(
            f"FantasyGP latest completed round is {round_number}, behind source Round {base_latest.round:02d}."
        )
    if round_number > base_latest.round + 1:
        raise RacePackError(
            f"FantasyGP is at Round {round_number:02d} but source data ends at Round {base_latest.round:02d}. "
            "The workflow will not invent skipped cumulative history."
        )

    individual_map = _manager_map(individual)
    cumulative_map = _manager_map(cumulative)
    if set(individual_map) != set(cumulative_map):
        raise RacePackError("Source individual and cumulative CSV manager sets do not match.")

    race_tuple = tuple(race_rows)
    standings_tuple = tuple(standings_rows)
    race_map = _row_map(race_tuple)
    standings_map = _row_map(standings_tuple)
    if len(race_map) != len(race_tuple) or len(standings_map) != len(standings_tuple):
        raise RacePackError("FantasyGP snapshot contains duplicate managers.")
    if set(race_map) != set(standings_map):
        raise RacePackError("FantasyGP race and overall snapshots contain different manager sets.")
    if set(individual_map) != set(race_map):
        missing = sorted(set(individual_map) - set(race_map))
        unexpected = sorted(set(race_map) - set(individual_map))
        raise RacePackError(
            "FantasyGP competitor set differs from the season master. "
            f"Missing managers: {missing}; unexpected managers: {unexpected}."
        )
    if expected_competitors is not None and len(race_map) != expected_competitors:
        raise RacePackError(
            f"FantasyGP snapshot contains {len(race_map)} competitors; expected {expected_competitors}."
        )

    team_conflicts: list[str] = []
    for key in race_map:
        if race_map[key].team.casefold() != standings_map[key].team.casefold():
            team_conflicts.append(
                f"{race_map[key].manager}: race={race_map[key].team!r}, standings={standings_map[key].team!r}"
            )
    if team_conflicts:
        raise RacePackError("FantasyGP race/standings team-name conflicts: " + "; ".join(team_conflicts[:10]))

    output_individual = Path(output_individual_path)
    output_cumulative = Path(output_cumulative_path)

    if round_number == base_latest.round:
        mismatches: list[str] = []
        for key, base_race in individual_map.items():
            fetched_race = race_map[key]
            fetched_total = standings_map[key]
            if base_race.values[-1] != fetched_race.points:
                mismatches.append(
                    f"{base_race.manager} race points: CSV={base_race.values[-1]}, FantasyGP={fetched_race.points}"
                )
            base_total = cumulative_map[key]
            if base_total.values[-1] != fetched_total.points:
                mismatches.append(
                    f"{base_total.manager} total: CSV={base_total.values[-1]}, FantasyGP={fetched_total.points}"
                )
            if base_race.team.casefold() != fetched_race.team.casefold():
                mismatches.append(
                    f"{base_race.manager} team: CSV={base_race.team!r}, FantasyGP={fetched_race.team!r}"
                )
        if mismatches:
            raise RacePackError(
                "Existing latest round does not match FantasyGP. Review before replacing data. "
                + "; ".join(mismatches[:20])
            )
        write_dataset(individual, output_individual)
        write_dataset(cumulative, output_cumulative)
        return {
            "status": "no_change",
            "round": round_number,
            "race": race_name,
            "competitors": len(race_map),
            "renamed_teams": [],
        }

    header = f"{race_name.strip()} - Race {round_number:02d}"
    standings_order = sorted(
        standings_tuple,
        key=lambda row: (row.position, -row.points, row.team.casefold(), row.manager.casefold()),
    )
    renamed_teams: list[dict[str, str]] = []
    new_individual: list[Competitor] = []
    new_cumulative: list[Competitor] = []
    for standing in standings_order:
        key = standing.manager_key
        race = race_map[key]
        base_race = individual_map[key]
        base_total = cumulative_map[key]
        if base_race.team.casefold() != standing.team.casefold():
            renamed_teams.append(
                {"manager": standing.manager, "from": base_race.team, "to": standing.team}
            )
        new_individual.append(
            Competitor(standing.team, standing.manager, (*base_race.values, race.points))
        )
        new_cumulative.append(
            Competitor(standing.team, standing.manager, (*base_total.values, standing.points))
        )

    updated_individual = Dataset(
        (*individual.headers, header), tuple(new_individual), "FantasyGP authenticated update"
    )
    updated_cumulative = Dataset(
        (*cumulative.headers, header), tuple(new_cumulative), "FantasyGP authenticated update"
    )
    write_dataset(updated_individual, output_individual)
    write_dataset(updated_cumulative, output_cumulative)
    return {
        "status": "updated",
        "round": round_number,
        "race": race_name,
        "competitors": len(race_map),
        "renamed_teams": renamed_teams,
    }
