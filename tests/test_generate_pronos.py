import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from generate_pronos import (
    Panel,
    Selection,
    build_panels,
    evaluate_pick,
    merge_sheet_rows,
    panels_to_sheet_rows,
    quote_candidates,
    update_sheet_results,
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

    def test_odds_limits_include_the_boundary_values(self):
        event = event_fixture()
        for bookmaker in event["bookmakers"]:
            for outcome in bookmaker["markets"][0]["outcomes"]:
                if outcome["name"] == "Home FC":
                    outcome["price"] = 1.20
                elif outcome["name"] == "Away FC":
                    outcome["price"] = 1.50

        candidates = quote_candidates(event, "soccer_epl")

        by_pick = {candidate.pick: candidate for candidate in candidates}
        self.assertEqual(by_pick["Vainqueur 1"].odds, 1.20)
        self.assertEqual(by_pick["Vainqueur 2"].odds, 1.50)


class ResultTests(unittest.TestCase):
    def test_evaluates_winners_double_chance_and_totals(self):
        self.assertEqual(evaluate_pick("Vainqueur 1", 2, 1), "Gagné")
        self.assertEqual(evaluate_pick("Double Chance 2", 2, 1), "Perdu")
        self.assertEqual(evaluate_pick("Double chance 1X", 1, 1), "Gagné")
        self.assertEqual(evaluate_pick("Total +2,5", 2, 1), "Gagné")
        self.assertEqual(evaluate_pick("Total -2,5", 2, 1), "Perdu")

    def test_updates_completed_scores_only_for_present_competitions(self):
        class FakeWorksheet:
            title = "Matchs"

            def __init__(self):
                self.values = [
                    [
                        "Date", "Type de Case", "Statut global", "Discipline",
                        "Compétition", "Match", "Prono", "Cote", "Heure",
                        "Cote totale", "Résultat", "Score",
                    ],
                    [
                        "2026-11-23", "1", "À venir", "Football", "Premier League",
                        "Home FC - Away FC", "Vainqueur 1", "1,30", "17:00",
                        "1,30", "", "",
                    ],
                ]

            def get_all_values(self):
                return self.values

            def update(self, values, range_name, value_input_option):
                self.values = values

        worksheet = FakeWorksheet()
        scores = [
            {
                "id": "event-1",
                "sport_key": "soccer_epl",
                "completed": True,
                "home_team": "Home FC",
                "away_team": "Away FC",
                "scores": [
                    {"name": "Home FC", "score": "2"},
                    {"name": "Away FC", "score": "1"},
                ],
            }
        ]
        with patch("generate_pronos.open_google_worksheet", return_value=worksheet), patch(
            "generate_pronos.api_get", return_value=(scores, {})
        ) as api_get:
            changed = update_sheet_results("test-key")

        self.assertEqual(changed, 1)
        api_get.assert_called_once_with(
            "/sports/soccer_epl/scores",
            {"daysFrom": "2", "dateFormat": "iso"},
            "test-key",
        )
        self.assertEqual(worksheet.values[1][10:12], ["Gagné", "2 - 1"])
        self.assertEqual(worksheet.values[1][2], "Gagné")


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
        self.assertTrue(all(len(panel.selections) == 4 for panel in panels))

    def test_panels_use_four_football_picks_without_high_confidence_basketball(self):
        panels = build_panels(
            [selection(f"f-{i}") for i in range(12)]
            + [selection("b-weak", sport="Basketball", probability=0.70, odds=1.25)]
        )

        self.assertTrue(all(len(panel.selections) == 4 for panel in panels))
        self.assertTrue(
            all(sum(item.sport == "Football" for item in panel.selections) == 4 for panel in panels)
        )

    def test_sheet_merge_keeps_recent_history_and_locked_matches(self):
        now = datetime(2026, 11, 24, 8, tzinfo=timezone.utc)
        header = [
            "Date", "Type de Case", "Statut global", "Discipline",
            "Compétition", "Match", "Prono", "Cote", "Heure",
            "Cote totale", "Résultat", "Score",
        ]
        existing = [
            header,
            ["2026-11-13", "1", "Gagné", "Football", "Premier League", "Old - Match",
             "Vainqueur 1", "1,30", "12:00", "1,30", "Gagné", "1 - 0"],
            ["2026-11-24", "1", "En cours", "Football", "Premier League", "Locked - Match",
             "Vainqueur 1", "1,30", "07:00", "1,30", "", ""],
        ]
        generated = [
            header,
            ["2026-11-24", "1", "À venir", "Football", "Premier League", "Locked - Match",
             "Vainqueur 1", "1,30", "07:00", "1,30", "", ""],
            ["2026-11-25", "2", "À venir", "Football", "Premier League", "New - Match",
             "Vainqueur 1", "1,30", "12:00", "1,30", "", ""],
        ]

        merged = merge_sheet_rows(existing, generated, now)

        self.assertEqual(len(merged), 3)
        self.assertEqual(merged[1][5], "Locked - Match")
        self.assertEqual(merged[2][5], "New - Match")

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
