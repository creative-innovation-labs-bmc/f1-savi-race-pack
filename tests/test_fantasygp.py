from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from f1_savi.dataset import read_dataset
from f1_savi.fantasygp import (
    FantasyGPRow,
    combine_league_pages,
    rows_from_league_response,
    update_season_datasets,
)
from f1_savi.models import RacePackError


FIXTURES = Path(__file__).parent / "fixtures"
INDIVIDUAL = FIXTURES / "F1_Season2_Individual_R11_Hungary.csv"
CUMULATIVE = FIXTURES / "F1_Season2_Cumulative_R11_Hungary_GRAPH_FIXED.csv"


def snapshot_rows(*, next_round: bool = False) -> tuple[list[FantasyGPRow], list[FantasyGPRow]]:
    individual = read_dataset(INDIVIDUAL)
    cumulative = read_dataset(CUMULATIVE)
    cumulative_by_manager = {
        item.manager.casefold(): item for item in cumulative.competitors
    }
    race_rows: list[FantasyGPRow] = []
    standings_rows: list[FantasyGPRow] = []
    for index, competitor in enumerate(individual.competitors, start=1):
        total = cumulative_by_manager[competitor.manager.casefold()]
        race_points = 100 + (index % 37) if next_round else competitor.values[-1]
        total_points = total.values[-1] + race_points if next_round else total.values[-1]
        race_rows.append(
            FantasyGPRow(
                team=competitor.team,
                manager=competitor.manager,
                points=race_points,
                position=index,
                ranking=index,
                position_change=0,
            )
        )
        standings_rows.append(
            FantasyGPRow(
                team=competitor.team,
                manager=competitor.manager,
                points=total_points,
                position=index,
                ranking=index,
                position_change=0,
            )
        )
    return race_rows, standings_rows


def page_from_rows(rows: list[FantasyGPRow], *, offset: int, total: int) -> dict[str, object]:
    return {
        "howmany": len(rows),
        "total": total,
        "newoffset": offset + len(rows),
        "teamnames": [item.team for item in rows],
        "teamdisplay_names": [item.manager for item in rows],
        "teampoints": [str(item.points) for item in rows],
        "teampos": [str(item.position) for item in rows],
        "teamrankings": [str(item.ranking) for item in rows],
        "teamposchange": [str(item.position_change) for item in rows],
        "teamuids": [f"uid-{offset + index}" for index in range(len(rows))],
        "profilelinks": ["" for _ in rows],
    }


class FantasyGPResponseTests(unittest.TestCase):
    def test_parse_league_response(self) -> None:
        rows = [
            FantasyGPRow("Team A", "Manager A", 1234, 1, 1, 2),
            FantasyGPRow("Team B", "Manager B", 1200, 2, 2, -1),
        ]
        parsed = rows_from_league_response(page_from_rows(rows, offset=0, total=2))
        self.assertEqual([item.team for item in parsed], ["Team A", "Team B"])
        self.assertEqual(parsed[0].points, 1234)
        self.assertEqual(parsed[1].position_change, -1)

    def test_combine_two_pages(self) -> None:
        race_rows, _ = snapshot_rows()
        pages = [
            page_from_rows(race_rows[:25], offset=0, total=46),
            page_from_rows(race_rows[25:], offset=25, total=46),
        ]
        combined = combine_league_pages(pages, expected_competitors=46)
        self.assertEqual(len(combined), 46)
        self.assertEqual(combined[0].manager, "JR10044")
        self.assertEqual(combined[-1].manager, "AdrianoRS")

    def test_duplicate_manager_is_rejected(self) -> None:
        race_rows, _ = snapshot_rows()
        bad = list(race_rows)
        bad[-1] = FantasyGPRow(
            bad[-1].team,
            bad[0].manager,
            bad[-1].points,
            bad[-1].position,
            bad[-1].ranking,
            0,
        )
        pages = [
            page_from_rows(bad[:25], offset=0, total=46),
            page_from_rows(bad[25:], offset=25, total=46),
        ]
        with self.assertRaisesRegex(RacePackError, "duplicate managers"):
            combine_league_pages(pages, expected_competitors=46)


class FantasyGPUpdateTests(unittest.TestCase):
    def test_hungary_snapshot_is_valid_no_change(self) -> None:
        race_rows, standings_rows = snapshot_rows()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = update_season_datasets(
                INDIVIDUAL,
                CUMULATIVE,
                race_name="Hungary",
                round_number=11,
                race_rows=race_rows,
                standings_rows=standings_rows,
                output_individual_path=root / "individual.csv",
                output_cumulative_path=root / "cumulative.csv",
            )
            self.assertEqual(summary["status"], "no_change")
            self.assertEqual(read_dataset(root / "individual.csv").headers[-1], "Hungary - Race 11")
            self.assertEqual(read_dataset(root / "cumulative.csv").competitors[0].values[-1], 2080)

    def test_next_round_is_appended(self) -> None:
        race_rows, standings_rows = snapshot_rows(next_round=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = update_season_datasets(
                INDIVIDUAL,
                CUMULATIVE,
                race_name="Netherlands",
                round_number=12,
                race_rows=race_rows,
                standings_rows=standings_rows,
                output_individual_path=root / "individual.csv",
                output_cumulative_path=root / "cumulative.csv",
            )
            individual = read_dataset(root / "individual.csv")
            cumulative = read_dataset(root / "cumulative.csv")
            self.assertEqual(summary["status"], "updated")
            self.assertEqual(individual.headers[-1], "Netherlands - Race 12")
            self.assertEqual(cumulative.headers[-1], "Netherlands - Race 12")
            snoopy_race = next(item for item in individual.competitors if item.manager == "JR10044")
            snoopy_total = next(item for item in cumulative.competitors if item.manager == "JR10044")
            self.assertEqual(len(snoopy_race.values), 12)
            self.assertEqual(snoopy_total.values[-1], 2080 + snoopy_race.values[-1])

    def test_missing_competitor_is_rejected(self) -> None:
        race_rows, standings_rows = snapshot_rows(next_round=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RacePackError, "competitor set differs"):
                update_season_datasets(
                    INDIVIDUAL,
                    CUMULATIVE,
                    race_name="Netherlands",
                    round_number=12,
                    race_rows=race_rows[:-1],
                    standings_rows=standings_rows[:-1],
                    output_individual_path=root / "individual.csv",
                    output_cumulative_path=root / "cumulative.csv",
                )

    def test_skipped_round_is_rejected(self) -> None:
        race_rows, standings_rows = snapshot_rows(next_round=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RacePackError, "will not invent skipped"):
                update_season_datasets(
                    INDIVIDUAL,
                    CUMULATIVE,
                    race_name="Italy",
                    round_number=13,
                    race_rows=race_rows,
                    standings_rows=standings_rows,
                    output_individual_path=root / "individual.csv",
                    output_cumulative_path=root / "cumulative.csv",
                )

    def test_existing_round_mismatch_is_rejected(self) -> None:
        race_rows, standings_rows = snapshot_rows()
        race_rows[0] = FantasyGPRow(
            race_rows[0].team,
            race_rows[0].manager,
            race_rows[0].points + 1,
            race_rows[0].position,
            race_rows[0].ranking,
            0,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RacePackError, "does not match FantasyGP"):
                update_season_datasets(
                    INDIVIDUAL,
                    CUMULATIVE,
                    race_name="Hungary",
                    round_number=11,
                    race_rows=race_rows,
                    standings_rows=standings_rows,
                    output_individual_path=root / "individual.csv",
                    output_cumulative_path=root / "cumulative.csv",
                )


if __name__ == "__main__":
    unittest.main()
