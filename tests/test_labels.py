from __future__ import annotations

import unittest

from f1_savi.labels import normalise_display_label


class FantasyGPLabelTests(unittest.TestCase):
    def test_supporter_and_pro_icons_are_removed(self) -> None:
        self.assertEqual(
            normalise_display_label("PJF1<i class='fas fa-star pull-right' title='pro'> </i>"),
            "PJF1",
        )
        self.assertEqual(
            normalise_display_label("Andries<i class='fas fa-thumbs-up pull-right' title='supporter'> </i>"),
            "Andries",
        )

    def test_entities_and_whitespace_are_normalised(self) -> None:
        self.assertEqual(normalise_display_label(" Team&nbsp;Name  "), "Team Name")


if __name__ == "__main__":
    unittest.main()
