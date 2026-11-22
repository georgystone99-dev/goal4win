import unittest
from datetime import datetime, timezone

from generate_pronos import (
    Panel,
    Selection,
    build_panels,
    panels_to_sheet_rows,
    quote_candidates,
)


def event_fixture():
    bookmakers = []
    for index in range(3):
        bookmakers.append(
            {
                "key": f"book-{index}",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Home FC", "price": 1.30 + index * 0.01},
                            {"name": "Draw", "price": 5.0},
                            {"name": "Away FC", "price": 4.0},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "point": 2.5, "price": 1.40},
                            {"name": "Under", "point": 2.5, "price": 2.8},
                        ],
                    },
                ],
            }
        )
    return {
        "id": "event-1",
        "sport_key": "soccer_epl",
        "home_team": "Home FC",
        "away_team": "Away FC",
        "commence_time": "2026-11-23T17:00:00Z",
        "bookmakers": bookmakers,
    }


def selection(event_id, sport="Football", probability=0.7, odds=1.3):
    return Selection(
        event_id=event_id,
        home=f"Home {event_id}",
        away=f"Away {event_id}",
        sport=sport,
        competition="Test",
        commence_time=datetime(2026, 11, 23, 17, tzinfo=timezone.utc),
        pick="Vainqueur 1",
        odds=odds,
        probability=probability,
        bookmaker_count=3,
        consensus_spread=0.02,
        market="h2h",
    )


class QuoteTests(unittest.TestCase):
    def test_de_vigs_consensus_and_builds_french_market_labels(self):
        candidates = quote_candidates(event_fixture(), "soccer_epl")
        by_pick = {candidate.pick: candidate for candidate in candidates}

        self.assertIn("Vainqueur 1", by_pick)
        self.assertIn("Total +2,5", by_pick)
        self.assertEqual(by_pick["Vainqueur 1"].bookmaker_count, 3)
        self.assertGreater(by_pick["Vainqueur 1"].probability, 0.6)

    def test_odds_limits_are_strict(self):
        event = event_fixture()
        for bookmaker in event["bookmakers"]:
            for outcome in bookmaker["markets"][0]["outcomes"]:
                if outcome["name"] == "Home FC":
                    outcome["price"] = 1.20
                elif outcome["name"] == "Away FC":
                    outcome["price"] = 1.50

        candidates = quote_candidates(event, "soccer_epl")

        self.assertNotIn("Vainqueur 1", {candidate.pick for candidate in candidates})
        self.assertNotIn("Vainqueur 2", {candidate.pick for candidate in candidates})


class PanelTests(unittest.TestCase):
    def test_panels_are_unique_and_basketball_requires_high_confidence(self):
        football = [selection(f"f-{i}", probability=0.8 - i * 0.01) for i in range(12)]
        basketball = [
            selection("b-weak", sport="Basketball", probability=0.70, odds=1.40),
            selection("b-strong", sport="Basketball", probability=0.76, odds=1.40),
        ]
        panels = build_panels(football + basketball)

        all_selections = [item for panel in panels for item in panel.selections]
        self.assertEqual(len(all_selections), 12)
        self.assertEqual(len({item.event_id for item in all_selections}), 12)
        self.assertNotIn("b-weak", {item.event_id for item in all_selections})
        self.assertIn("b-strong", {item.event_id for item in all_selections})
        self.assertTrue(all(len(panel.selections) <= 4 for panel in panels))

    def test_sheet_rows_match_pwa_columns_and_time_format(self):
        panels = [Panel(number=1, selections=[selection("f-1")]),
                  Panel(number=2, selections=[]),
                  Panel(number=3, selections=[])]

        rows = panels_to_sheet_rows(panels)

        self.assertEqual(
            rows[0],
            [
                "Date", "Type de Case", "Statut global", "Discipline",
                "Compétition", "Match", "Prono", "Cote", "Heure",
                "Cote totale", "Résultat", "Score",
            ],
        )
        self.assertEqual(rows[1][8], "18:00")
        self.assertEqual(rows[1][5], "Home f-1 - Away f-1")


if __name__ == "__main__":
    unittest.main()
