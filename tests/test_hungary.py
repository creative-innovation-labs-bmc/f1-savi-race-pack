from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from f1_savi.core import (
    RacePackError,
    build_payload,
    build_race_pack,
    calculate_adjustments,
    read_dataset,
    validate_inputs,
    verify_manifest,
)

FIXTURES = Path(__file__).parent / "fixtures"
INDIVIDUAL = FIXTURES / "F1_Season2_Individual_R11_Hungary.csv"
CUMULATIVE = FIXTURES / "F1_Season2_Cumulative_R11_Hungary_GRAPH_FIXED.csv"


class HungaryReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.individual = read_dataset(INDIVIDUAL)
        cls.cumulative = read_dataset(CUMULATIVE)
        cls.payload = build_payload(cls.individual, cls.cumulative, expected_competitors=46)

    def test_input_qc_passes_and_preserves_authoritative_cumulative(self) -> None:
        report = validate_inputs(self.individual, self.cumulative, expected_competitors=46)
        self.assertEqual(report.status, "pass")
        self.assertEqual(report.checks["individual_rows"], 46)
        self.assertEqual(report.checks["cumulative_rows"], 46)
        self.assertGreater(report.checks["non_zero_adjustments"], 0)
        self.assertIn("authoritative", report.warnings[0])

    def test_latest_round_metadata(self) -> None:
        self.assertEqual(self.payload["metadata"]["round"], 11)
        self.assertEqual(self.payload["metadata"]["race"], "Hungary")

    def test_hungary_race_top_ten_and_tie_ranking(self) -> None:
        top = self.payload["race_top"]
        expected = [
            (1, "We are the competition", "lou-mih", 159),
            (2, "vansF1", "Andries", 156),
            (3, "Save The Engine", "RichardS", 151),
            (4, "Machined Wheel Nut", "Jean Alesi", 138),
            (5, "Blue Flag Racing", "pgmotts", 136),
            (5, "Maximum Points", "Max Cutter", 136),
            (7, "Renault F1", "PJF1", 134),
            (8, "Box Box Box", "fooch", 131),
            (9, "CrashBangWallop", "Simon Rogerson", 128),
            (10, "Magraith Motorsport", "Matt Magraith", 122),
        ]
        actual = [(item["rank"], item["team"], item["manager"], item["points"]) for item in top]
        self.assertEqual(actual, expected)

    def test_authoritative_overall_top_ten(self) -> None:
        expected = [
            (1, "Snoopy", 2080),
            (2, "Maximum Points", 2056),
            (3, "Renault F1", 1959),
            (4, "Box Box Box", 1954),
            (5, "We are the competition", 1925),
            (6, "AloeVira", 1916),
            (7, "Magraith Motorsport", 1844),
            (8, "Bravo Fernando", 1813),
            (9, "The Vans", 1802),
            (10, "CrashBangWallop", 1801),
        ]
        actual = [(item["rank"], item["team"], item["points"]) for item in self.payload["overall_top"]]
        self.assertEqual(actual, expected)

    def test_biggest_mover_and_drop(self) -> None:
        mover = self.payload["biggest_movers"][0]
        drop = self.payload["biggest_drops"][0]
        self.assertEqual((mover["team"], mover["movement"]), ("vansF1", 6))
        self.assertEqual((drop["team"], drop["movement"]), ("I thought this was Mario Kart", -4))

    def test_podium_tally_updates_after_hungary(self) -> None:
        tally = {item["team"]: item for item in self.payload["podium_tally"]}
        self.assertEqual((tally["We are the competition"]["first"], tally["We are the competition"]["first_change"]), (2, 1))
        self.assertEqual((tally["vansF1"]["second"], tally["vansF1"]["second_change"]), (2, 1))
        self.assertEqual((tally["Save The Engine"]["third"], tally["Save The Engine"]["third_change"]), (1, 1))
        self.assertEqual(tally["Snoopy"]["total"], 4)

    def test_known_cumulative_corrections_are_recorded(self) -> None:
        adjustments = calculate_adjustments(self.individual, self.cumulative)
        lookup = {(item.round, item.team): item.adjustment for item in adjustments}
        self.assertEqual(lookup[(7, "Snoopy")], 13)
        self.assertEqual(lookup[(10, "We are the competition")], -20)
        self.assertEqual(lookup[(11, "Snoopy")], 0)

    def test_full_pack_build_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "round-11"
            build_race_pack(INDIVIDUAL, CUMULATIVE, output)
            manifest = verify_manifest(output)
            self.assertEqual(manifest["round"], 11)
            self.assertTrue((output / "Teams_Update.html").exists())
            self.assertTrue((output / "Teams_Update.txt").exists())
            self.assertTrue((output / "race_data.json").exists())
            data = json.loads((output / "race_data.json").read_text(encoding="utf-8"))
            self.assertEqual(data["qc"]["status"], "pass")
            with (output / "race_top_10.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[1], ["1", "We are the competition", "lou-mih", "159"])

    def test_manifest_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "round-11"
            build_race_pack(INDIVIDUAL, CUMULATIVE, output)
            (output / "Teams_Update.txt").write_text("changed", encoding="utf-8")
            with self.assertRaises(RacePackError):
                verify_manifest(output)


if __name__ == "__main__":
    unittest.main()
