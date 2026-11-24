from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
from io import StringIO
import unittest
from unittest.mock import patch

from generate_pronos import (
    Panel,
    Selection,
    SHEET_HEADERS,
    active_sports,
    build_panels,
    build_daily_panels,
    date_is_complete,
    evaluate_pick,
    fetch_daily_panels,
    merge_sheet_rows,
    panels_to_sheet_rows,
    quote_candidates,
    update_sheet_results,
    write_google_sheet,
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
                            {"name": "Over", "point": 1.5, "price": 1.40},
                            {"name": "Under", "point": 1.5, "price": 3.0},
                            {"name": "Over", "point": 2.5, "price": 1.40},
                            {"name": "Under", "point": 2.5, "price": 2.8},
                            {"name": "Over", "point": 3.5, "price": 2.7},
                            {"name": "Under", "point": 3.5, "price": 1.30},
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
        self.assertIn("Total +1,5", by_pick)
        self.assertIn("Total -3,5", by_pick)
        self.assertNotIn("Total +2,5", by_pick)
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
            for outcome in bookmaker["markets"][1]["outcomes"]:
                if outcome["name"] == "Over" and outcome["point"] == 1.5:
                    outcome["price"] = 1.20
                elif outcome["name"] == "Under" and outcome["point"] == 3.5:
                    outcome["price"] = 1.50

        candidates = quote_candidates(event, "soccer_epl")

        by_pick = {candidate.pick: candidate for candidate in candidates}
        self.assertEqual(by_pick["Vainqueur 1"].odds, 1.20)
        self.assertEqual(by_pick["Vainqueur 2"].odds, 1.50)
        self.assertEqual(by_pick["Total +1,5"].odds, 1.20)
        self.assertEqual(by_pick["Total -3,5"].odds, 1.50)


class ResultTests(unittest.TestCase):
    def test_evaluates_winners_double_chance_and_totals(self):
        self.assertEqual(evaluate_pick("Vainqueur 1", 2, 1), "Gagné")
        self.assertEqual(evaluate_pick("Double Chance 2", 2, 1), "Perdu")
        self.assertEqual(evaluate_pick("Double chance 1X", 1, 1), "Gagné")
        self.assertEqual(evaluate_pick("Total +2,5", 2, 1), "Gagné")
        self.assertEqual(evaluate_pick("Total -2,5", 2, 1), "Perdu")

    def test_evaluates_half_goal_totals_on_both_sides_of_the_line(self):
        self.assertEqual(evaluate_pick("Total +1,5", 1, 0), "Perdu")
        self.assertEqual(evaluate_pick("Total +1,5", 1, 1), "Gagné")
        self.assertEqual(evaluate_pick("Total +1.5", 1, 1), "Gagné")
        self.assertEqual(evaluate_pick("Total -3,5", 2, 1), "Gagné")
        self.assertEqual(evaluate_pick("Total -3.5", 2, 2), "Perdu")

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
            selection("b-expensive", sport="Basketball", probability=0.80, odds=1.40),
            selection("b-strong", sport="Basketball", probability=0.76, odds=1.30),
        ]
        panels = build_panels(football + basketball)

        all_selections = [item for panel in panels for item in panel.selections]
        self.assertEqual(len(all_selections), 12)
        self.assertEqual(len({item.event_id for item in all_selections}), 12)
        self.assertNotIn("b-weak", {item.event_id for item in all_selections})
        self.assertNotIn("b-expensive", {item.event_id for item in all_selections})
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

    def test_active_sports_discovers_active_soccer_and_supported_basketball(self):
        response = [
            {"key": "soccer_new_league", "group": "Soccer", "title": "New League", "active": True},
            {"key": "soccer_epl", "group": "Soccer", "title": "Premier League", "active": True},
            {"key": "soccer_italy_serie_b", "group": "Soccer", "title": "Serie B", "active": True},
            {"key": "soccer_inactive", "group": "Soccer", "title": "Inactive", "active": False},
            {"key": "basketball_nba", "group": "Basketball", "title": "NBA", "active": True},
            {"key": "basketball_euroleague", "group": "Basketball", "title": "EuroLeague", "active": True},
            {"key": "basketball_ncaab", "group": "Basketball", "title": "NCAAB", "active": True},
            {"key": "americanfootball_nfl", "group": "Soccer", "title": "NFL", "active": True},
            {"key": "baseball_mlb", "group": "Basketball", "title": "MLB", "active": True},
            {"key": "football_soccer_league", "group": "Soccer", "title": "Wrong prefix", "active": True},
        ]
        with patch("generate_pronos.api_get", return_value=(response, {})) as api_get:
            sports = active_sports("test-key")

        self.assertEqual(
            list(sports),
            [
                "soccer_epl", "soccer_italy_serie_b", "soccer_new_league",
                "basketball_nba", "basketball_euroleague",
            ],
        )
        self.assertEqual(sports["soccer_new_league"], ("Football", "New League"))
        api_get.assert_called_once_with("/sports", {}, "test-key")

    def test_sheet_date_requires_three_complete_unique_panels(self):
        panel_rows = {
            "1": [["2026-11-24", "1", "", "", "", f"Home {i} - Away {i}"] for i in range(4)],
            "2": [["2026-11-24", "2", "", "", "", f"Home {i + 4} - Away {i + 4}"] for i in range(4)],
            "3": [["2026-11-24", "3", "", "", "", f"Home {i + 8} - Away {i + 8}"] for i in range(4)],
        }

        self.assertTrue(date_is_complete(panel_rows))
        panel_rows["3"].pop()
        self.assertFalse(date_is_complete(panel_rows))

    def test_daily_panels_fill_only_missing_slots_for_incomplete_dates(self):
        existing = {
            "1": [["2026-11-24", "1", "À venir", "Football", "Test",
                   "Home existing - Away existing"]],
            "2": [],
            "3": [],
        }
        candidates = [
            selection("existing", probability=0.9),
            *[selection(f"new-{index}", probability=0.8 - index * 0.01) for index in range(12)],
        ]
        candidates[0] = replace(
            candidates[0], home="Home existing", away="Away existing"
        )

        panels = build_daily_panels(candidates, existing)

        self.assertEqual([len(panel.selections) for panel in panels], [3, 4, 4])
        self.assertNotIn(
            "existing",
            {item.event_id for panel in panels for item in panel.selections},
        )

    def test_daily_panels_use_two_basketball_picks_when_football_is_sparse(self):
        candidates = [selection(f"f-{index}") for index in range(6)]
        candidates.extend(
            selection(
                f"b-{index}",
                sport="Basketball",
                probability=0.80,
                odds=1.30,
            )
            for index in range(6)
        )

        panels = build_daily_panels(candidates, {})

        self.assertTrue(all(len(panel.selections) == 4 for panel in panels))
        self.assertTrue(
            all(
                sum(item.sport == "Basketball" for item in panel.selections) == 2
                for panel in panels
            )
        )
        self.assertEqual(
            len({item.event_id for panel in panels for item in panel.selections}),
            12,
        )

    def test_daily_fetch_keeps_available_picks_and_warns_after_sport_stats(self):
        match_date = datetime(2026, 11, 24, 12, tzinfo=timezone.utc).date()
        event = event_fixture()
        event["commence_time"] = "2026-11-24T17:00:00Z"

        def fake_api_get(path, params, api_key):
            return ([event], {}) if path.endswith("/events") else ([event], {})

        output = StringIO()
        with patch("generate_pronos.api_get", side_effect=fake_api_get), redirect_stdout(output):
            panels_by_date, _, _ = fetch_daily_panels(
                "test-key",
                [match_date],
                datetime(2026, 11, 24, 8, tzinfo=timezone.utc),
                {"soccer_epl": ("Football", "Premier League")},
                [],
            )

        self.assertEqual(
            [len(panel.selections) for panel in panels_by_date[match_date]],
            [1, 0, 0],
        )
        log = output.getvalue()
        self.assertLess(log.index("sélection(s) admissible(s)"), log.index("Avertissement"))
        self.assertIn("seront tout de même publiés", log)

    def test_daily_fetch_stops_after_twelve_picks_for_date(self):
        match_date = datetime(2026, 11, 24, 12, tzinfo=timezone.utc).date()
        events = []
        for index in range(12):
            event = event_fixture()
            event["id"] = f"event-{index}"
            event["home_team"] = f"Home {index}"
            event["away_team"] = f"Away {index}"
            event["commence_time"] = f"2026-11-24T{12 + index % 8:02}:00:00Z"
            for bookmaker in event["bookmakers"]:
                for outcome in bookmaker["markets"][0]["outcomes"]:
                    if outcome["name"] == "Home FC":
                        outcome["name"] = event["home_team"]
                    elif outcome["name"] == "Away FC":
                        outcome["name"] = event["away_team"]
            events.append(event)

        def fake_api_get(path, params, api_key):
            return (events, {}) if path.endswith("/events") else (events, {"x-requests-remaining": "499"})

        with patch("generate_pronos.api_get", side_effect=fake_api_get) as api_get:
            panels_by_date, remaining, request_count = fetch_daily_panels(
                "test-key",
                [match_date],
                datetime(2026, 11, 24, 8, tzinfo=timezone.utc),
                {"soccer_epl": ("Football", "Premier League")},
                [],
            )

        self.assertTrue(all(len(panel.selections) == 4 for panel in panels_by_date[match_date]))
        self.assertEqual(request_count, 1)
        self.assertEqual(remaining, ["499"])
        self.assertEqual(api_get.call_count, 2)

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

    def test_sheet_merge_preserves_full_days_and_accepts_after_tomorrow(self):
        now = datetime(2026, 11, 24, 8, tzinfo=timezone.utc)
        header = [
            "Date", "Type de Case", "Statut global", "Discipline",
            "Compétition", "Match", "Prono", "Cote", "Heure",
            "Cote totale", "Résultat", "Score",
        ]
        existing = [header]
        for panel in ("1", "2", "3"):
            for index in range(4):
                number = (int(panel) - 1) * 4 + index
                existing.append(
                    [
                        "2026-11-24", panel, "À venir", "Football", "Premier League",
                        f"Home {number} - Away {number}", "Vainqueur 1", "1,30",
                        "18:00", "1,30", "", "",
                    ]
                )
        generated = [
            header,
            ["2026-11-24", "1", "À venir", "Football", "Premier League",
             "Replacement - Match", "Vainqueur 1", "1,30", "19:00", "1,30", "", ""],
            ["2026-11-26", "1", "À venir", "Football", "Premier League",
             "New Day - Match", "Vainqueur 1", "1,30", "19:00", "1,30", "", ""],
            ["2026-11-27", "1", "À venir", "Football", "Premier League",
             "Outside Window - Match", "Vainqueur 1", "1,30", "19:00", "1,30", "", ""],
        ]

        merged = merge_sheet_rows(existing, generated, now)

        self.assertEqual(len(merged), 14)
        self.assertEqual(merged[1:], existing[1:] + [generated[2]])

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

    def test_locked_incomplete_date_is_reported_without_failing_or_writing(self):
        class FakeWorksheet:
            title = "Matchs"

            def __init__(self):
                self.values = [
                    list(SHEET_HEADERS),
                    [
                        "2026-11-24", "1", "En cours", "Football",
                        "Premier League", "Locked - Match", "Vainqueur 1",
                        "1,30", "07:00", "1,30", "", "",
                    ],
                ]
                self.updates = 0

            def get_all_values(self):
                return self.values

            def update(self, **kwargs):
                self.updates += 1

        worksheet = FakeWorksheet()
        rows = [list(SHEET_HEADERS)]
        for panel in ("1", "2", "3"):
            for index in range(4):
                rows.append(
                    [
                        "2026-11-24", panel, "À venir", "Football",
                        "Premier League", f"Home {panel}-{index} - Away {panel}-{index}",
                        "Vainqueur 1", "1,30", "18:00", "1,30", "", "",
                    ]
                )
        output = StringIO()

        with redirect_stdout(output):
            write_google_sheet(
                rows,
                datetime(2026, 11, 24, 8, tzinfo=timezone.utc),
                worksheet,
                [datetime(2026, 11, 24).date()],
            )

        self.assertIn("Information :", output.getvalue())
        self.assertIn("verrouillés", output.getvalue())
        self.assertEqual(worksheet.updates, 0)


if __name__ == "__main__":
    unittest.main()
