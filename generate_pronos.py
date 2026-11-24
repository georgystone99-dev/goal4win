#!/usr/bin/env python3
"""Generate objective Goal4win selections from The Odds API."""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo


API_BASE = "https://api.the-odds-api.com/v4"
TIMEZONE = ZoneInfo("Africa/Douala")
MARKETS = ("h2h", "totals")
API_REQUEST_DELAY = 1.2
API_RATE_LIMIT_RETRY_DELAY = 3
MIN_ODDS = 1.20
MAX_ODDS = 1.50
MIN_BOOKMAKERS = 3
MIN_BASKETBALL_PROBABILITY = 0.75
MAX_CONSENSUS_SPREAD = 0.06
SHEET_HEADERS = (
    "Date",
    "Type de Case",
    "Statut global",
    "Discipline",
    "Compétition",
    "Match",
    "Prono",
    "Cote",
    "Heure",
    "Cote totale",
    "Résultat",
    "Score",
)

SPORTS = {
    "soccer_epl": ("Football", "Premier League"),
    "soccer_spain_la_liga": ("Football", "Liga"),
    "soccer_germany_bundesliga": ("Football", "Bundesliga"),
    "soccer_italy_serie_a": ("Football", "Serie A"),
    "soccer_italy_serie_b": ("Football", "Serie B"),
    "soccer_france_ligue_one": ("Football", "Ligue 1"),
    "soccer_france_ligue_two": ("Football", "Ligue 2"),
    "soccer_germany_bundesliga2": ("Football", "2. Bundesliga"),
    "soccer_spain_segunda_division": ("Football", "Segunda División"),
    "soccer_uefa_champs_league": ("Football", "Ligue des champions"),
    "soccer_uefa_europa_league": ("Football", "Ligue Europa"),
    "soccer_uefa_europa_conference_league": ("Football", "Ligue Conférence"),
    "soccer_uefa_nations_league": ("Football", "Ligue des Nations"),
    "soccer_fifa_world_cup_qualifiers_europe": ("Football", "Qualifications Coupe du Monde"),
    "soccer_uefa_european_championship": ("Football", "Euro"),
    "soccer_fifa_world_cup": ("Football", "Coupe du Monde"),
    "soccer_portugal_primeira_liga": ("Football", "Primeira Liga"),
    "soccer_netherlands_eredivisie": ("Football", "Eredivisie"),
    "soccer_belgium_first_div": ("Football", "First Division A"),
    "soccer_turkey_super_league": ("Football", "Süper Lig"),
    "soccer_efl_champ": ("Football", "Championship"),
    "soccer_fa_cup": ("Football", "FA Cup"),
    "soccer_england_efl_cup": ("Football", "EFL Cup"),
    "soccer_italy_coppa_italia": ("Football", "Coppa Italia"),
    "soccer_spain_copa_del_rey": ("Football", "Copa del Rey"),
    "soccer_germany_dfb_pokal": ("Football", "DFB-Pokal"),
    "soccer_france_coupe_de_france": ("Football", "Coupe de France"),
    "soccer_spl": ("Football", "Scottish Premiership"),
    "soccer_switzerland_superleague": ("Football", "Swiss Super League"),
    "soccer_austria_bundesliga": ("Football", "Austrian Bundesliga"),
    "soccer_greece_super_league": ("Football", "Super League"),
    "soccer_norway_eliteserien": ("Football", "Eliteserien"),
    "soccer_sweden_allsvenskan": ("Football", "Allsvenskan"),
    "soccer_denmark_superliga": ("Football", "Superliga"),
    "soccer_poland_ekstraklasa": ("Football", "Ekstraklasa"),
    "basketball_nba": ("Basketball", "NBA"),
    "basketball_euroleague": ("Basketball", "EuroLeague"),
}
ODDS_COMPETITION_PRIORITY = (
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_portugal_primeira_liga",
    "soccer_netherlands_eredivisie",
    "soccer_belgium_first_div",
    "soccer_turkey_super_league",
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league",
    "basketball_nba",
    "basketball_euroleague",
    "soccer_fifa_world_cup",
    "soccer_uefa_nations_league",
)
MAX_ODDS_REQUESTS_PER_RUN = 12
SPORT_BY_COMPETITION = {
    competition.casefold(): sport_key
    for sport_key, (_, competition) in SPORTS.items()
}
DEFAULT_SPREADSHEET_ID = "11t2NRQYociuLCvE-VzicXg282XxTXDctM7oychcH5cQ"


@dataclass(frozen=True)
class Selection:
    event_id: str
    home: str
    away: str
    sport: str
    competition: str
    commence_time: datetime
    pick: str
    odds: float
    probability: float
    bookmaker_count: int
    consensus_spread: float
    market: str

    @property
    def strong_consensus(self) -> bool:
        return (
            self.bookmaker_count >= MIN_BOOKMAKERS
            and self.consensus_spread <= MAX_CONSENSUS_SPREAD
        )


@dataclass
class Panel:
    number: int
    selections: list[Selection]

    @property
    def total_odds(self) -> float:
        total = 1.0
        for selection in self.selections:
            total *= selection.odds
        return total


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Horodatage sans fuseau reçu de l’API : {value}")
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def api_get(path: str, params: dict[str, str], api_key: str) -> tuple[Any, dict[str, str]]:
    query = urlencode({**params, "apiKey": api_key})
    request_url = f"{API_BASE}{path}?{query}"
    rate_limit_retry = False
    while True:
        time.sleep(API_REQUEST_DELAY)
        try:
            with urlopen(request_url, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
                headers = {key.lower(): value for key, value in response.headers.items()}
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace").strip()
            exc.close()
            if (
                exc.code == 429
                and "EXCEEDED_FREQ_LIMIT" in message
                and not rate_limit_retry
            ):
                rate_limit_retry = True
                time.sleep(API_RATE_LIMIT_RETRY_DELAY)
                continue
            raise RuntimeError(
                f"The Odds API a renvoyé HTTP {exc.code} pour {path}: "
                f"{message or exc.reason}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                f"Connexion à The Odds API impossible : {exc.reason}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Réponse JSON invalide de The Odds API ({path}).") from exc
        return payload, headers


def active_sports(api_key: str) -> dict[str, tuple[str, str]]:
    """Return active competitions from the prioritized odds list."""
    payload, _ = api_get("/sports", {}, api_key)
    if not isinstance(payload, list):
        raise RuntimeError("Réponse inattendue de l’API pour /sports.")

    discovered: dict[str, tuple[str, str]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", ""))
        if key not in ODDS_COMPETITION_PRIORITY:
            continue
        sport = SPORTS[key][0], str(item.get("title") or key)
        SPORT_BY_COMPETITION[sport[1].casefold()] = key
        if item.get("active") is True:
            discovered[key] = sport

    return {
        key: discovered[key]
        for key in ODDS_COMPETITION_PRIORITY
        if key in discovered
    }


def date_window(match_date: date, now: datetime) -> tuple[datetime, datetime]:
    local_start = datetime.combine(match_date, datetime_time.min, tzinfo=TIMEZONE)
    local_end = datetime.combine(
        match_date + timedelta(days=1), datetime_time.min, tzinfo=TIMEZONE
    )
    start = max(now, local_start.astimezone(timezone.utc))
    end = local_end.astimezone(timezone.utc) - timedelta(seconds=1)
    return start, end


def sheet_date_counts(rows: list[list[str]]) -> dict[str, dict[str, list[list[str]]]]:
    if not rows:
        return {}
    indexes = {normalized(name): index for index, name in enumerate(rows[0])}
    date_index = indexes.get("date", -1)
    panel_index = indexes.get("type de case", -1)
    if date_index < 0 or panel_index < 0:
        raise RuntimeError("Colonnes Date et Type de Case introuvables dans Google Sheets.")

    grouped: dict[str, dict[str, list[list[str]]]] = {}
    for row in rows[1:]:
        if date_index >= len(row) or panel_index >= len(row):
            continue
        match_date = _sheet_date(row[date_index])
        if match_date is not None:
            grouped.setdefault(match_date.isoformat(), {}).setdefault(
                row[panel_index].strip(), []
            ).append(row)
    return grouped


def date_is_complete(panel_rows: dict[str, list[list[str]]]) -> bool:
    if set(panel_rows) != {"1", "2", "3"}:
        return False
    matches = [
        fixture_key_from_match(row[5].strip())
        for rows in panel_rows.values()
        for row in rows
        if len(row) > 5 and row[5].strip()
    ]
    return (
        all(len(panel_rows[number]) == 4 for number in ("1", "2", "3"))
        and len(matches) == 12
        and len({normalized(match) for match in matches}) == 12
    )


def fetch_daily_panels(
    api_key: str,
    target_dates: list[date],
    now: datetime,
    sports: dict[str, tuple[str, str]],
    existing_rows: list[list[str]],
) -> tuple[dict[date, list[Panel]], list[str], int]:
    grouped = sheet_date_counts(existing_rows)
    panels_by_date: dict[date, list[Panel]] = {}
    remaining: list[str] = []
    odds_requests = 0

    for match_date in target_dates:
        if odds_requests >= MAX_ODDS_REQUESTS_PER_RUN:
            print(
                f"Information : quota de {MAX_ODDS_REQUESTS_PER_RUN} requêtes de "
                f"cotes atteint ; le {match_date.isoformat()} est ignoré."
            )
            continue
        existing_for_date = grouped.get(match_date.isoformat(), {})
        if existing_for_date:
            if not date_is_complete(existing_for_date):
                print(
                    f"Information : le {match_date.isoformat()} est déjà présent "
                    "dans Google Sheets ; aucun appel API ni modification."
                )
            continue

        start, end = date_window(match_date, now)
        if end < start:
            continue
        day_events: list[dict[str, Any]] = []
        sport_stats: list[tuple[str, int]] = []
        panels: list[Panel] = []
        for sport_key in sports:
            if odds_requests >= MAX_ODDS_REQUESTS_PER_RUN:
                break
            params = {
                "dateFormat": "iso",
                "commenceTimeFrom": iso_utc(start),
                "commenceTimeTo": iso_utc(end),
            }
            event_payload, _ = api_get(
                f"/sports/{sport_key}/events", params, api_key
            )
            if not isinstance(event_payload, list):
                raise RuntimeError(
                    f"Réponse inattendue de l’API pour {sport_key}/events."
                )
            if not event_payload:
                sport_stats.append((sport_key, 0))
                continue

            odds_params = {
                **params,
                "regions": "eu",
                "markets": ",".join(MARKETS),
                "oddsFormat": "decimal",
            }
            odds_payload, headers = api_get(
                f"/sports/{sport_key}/odds", odds_params, api_key
            )
            odds_requests += 1
            if not isinstance(odds_payload, list):
                raise RuntimeError(
                    f"Réponse inattendue de l’API pour {sport_key}/odds."
                )
            if headers.get("x-requests-remaining") is not None:
                remaining.append(headers["x-requests-remaining"])
            sport_events = [
                event
                for event in odds_payload
                if isinstance(event, dict)
                and is_in_window(event.get("commence_time"), start, end)
            ]
            day_events.extend(sport_events)
            sport_selections = selections_from_events(sport_events, sports)
            sport_stats.append(
                (
                    sport_key,
                    sum(
                        selection.commence_time.astimezone(TIMEZONE).date()
                        == match_date
                        for selection in sport_selections
                    ),
                )
            )
            selections = selections_from_events(day_events, sports)
            day_selections = [
                selection
                for selection in selections
                if selection.commence_time.astimezone(TIMEZONE).date() == match_date
            ]
            panels = build_daily_panels(day_selections, existing_for_date)
            if all(
                len(existing_for_date.get(str(panel.number), []))
                + len(panel.selections)
                == 4
                for panel in panels
            ):
                break

        for sport_key, selection_count in sport_stats:
            print(
                f"{match_date.isoformat()} / {sport_key}: "
                f"{selection_count} sélection(s) admissible(s)."
            )
        day_selections = [
            selection for selection in selections_from_events(day_events, sports)
            if selection.commence_time.astimezone(TIMEZONE).date() == match_date
        ]
        panels = build_daily_panels(day_selections, existing_for_date)
        selected_matches = {
            fixture_key_from_match(row[5])
            for rows in existing_for_date.values()
            for row in rows
            if len(row) > 5 and row[5].strip()
        }
        selected_matches.update(
            fixture_key(selection.home, selection.away)
            for panel in panels
            for selection in panel.selections
        )
        selected_count = len(selected_matches)
        if selected_count < 12:
            print(
                f"Avertissement : {selected_count} sélection(s) unique(s) seulement "
                f"pour le {match_date.isoformat()} ; les panneaux disponibles "
                "seront tout de même publiés."
            )
        panels_by_date[match_date] = panels
    return panels_by_date, remaining, odds_requests


def is_in_window(value: Any, start: datetime, end: datetime) -> bool:
    if not isinstance(value, str):
        return False
    try:
        commence_time = parse_datetime(value)
    except ValueError:
        return False
    return start <= commence_time <= end


def outcome_key(name: str, home: str, away: str) -> str | None:
    normalized = name.strip().casefold()
    if normalized == home.strip().casefold():
        return "home"
    if normalized == away.strip().casefold():
        return "away"
    if normalized in {"draw", "tie"}:
        return "draw"
    if normalized == "over":
        return "over"
    if normalized == "under":
        return "under"
    return None


def fixture_key(home: str, away: str) -> str:
    return "|".join(sorted((normalized(home), normalized(away))))


def fixture_key_from_match(value: str) -> str:
    teams = value.split(" - ", 1)
    if len(teams) != 2:
        return normalized(value)
    return fixture_key(teams[0], teams[1])


def market_groups(event: dict[str, Any]) -> dict[tuple[str, float | None], dict[str, dict[str, float]]]:
    home = str(event.get("home_team", ""))
    away = str(event.get("away_team", ""))
    groups: dict[tuple[str, float | None], dict[str, dict[str, float]]] = {}
    for bookmaker in event.get("bookmakers", []):
        bookmaker_key = str(bookmaker.get("key") or bookmaker.get("title") or "")
        for market in bookmaker.get("markets", []):
            market_key = market.get("key")
            if market_key not in MARKETS:
                continue
            for outcome in market.get("outcomes", []):
                name = str(outcome.get("name", ""))
                key = outcome_key(name, home, away)
                if key is None:
                    continue
                point = None
                if market_key == "totals":
                    try:
                        point = float(outcome["point"])
                    except (KeyError, TypeError, ValueError):
                        continue
                try:
                    price = float(outcome["price"])
                except (KeyError, TypeError, ValueError):
                    continue
                if price <= 1:
                    continue
                group = groups.setdefault((market_key, point), {})
                prices = group.setdefault(bookmaker_key, {})
                prices[key] = price
    return groups


def quote_candidates(
    event: dict[str, Any],
    sport_key: str,
    sports: dict[str, tuple[str, str]] | None = None,
) -> list[Selection]:
    try:
        commence_time = parse_datetime(str(event["commence_time"]))
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Match sans heure de début valide : {event!r}") from exc
    sport, competition = (sports or SPORTS)[sport_key]
    home = str(event.get("home_team", ""))
    away = str(event.get("away_team", ""))
    expected_h2h = {"home", "away", "draw"} if sport == "Football" else {"home", "away"}
    candidates: list[Selection] = []

    for (market_key, point), bookmaker_prices in market_groups(event).items():
        expected = expected_h2h if market_key == "h2h" else {"over", "under"}
        valid_books = [
            prices
            for prices in bookmaker_prices.values()
            if expected.issubset(prices)
        ]
        if len(valid_books) < MIN_BOOKMAKERS:
            continue
        fair_by_book = []
        for prices in valid_books:
            reciprocal_sum = sum(1 / prices[key] for key in expected)
            fair_by_book.append(
                {key: (1 / prices[key]) / reciprocal_sum for key in expected}
            )

        for key in expected:
            if (
                sport == "Football"
                and market_key == "totals"
                and not (
                    (key == "over" and point == 1.5)
                    or (key == "under" and point == 3.5)
                )
            ):
                continue
            quotes = [prices[key] for prices in valid_books]
            average_odds = statistics.mean(quotes)
            if not MIN_ODDS <= average_odds <= MAX_ODDS:
                continue
            probabilities = [fair[key] for fair in fair_by_book]
            if market_key == "h2h":
                pick = {"home": "Vainqueur 1", "away": "Vainqueur 2", "draw": "Match nul"}[key]
            else:
                sign = "+" if key == "over" else "-"
                pick = f"Total {sign}{format_line(float(point))}"
            candidates.append(
                Selection(
                    event_id=str(event.get("id", "")),
                    home=home,
                    away=away,
                    sport=sport,
                    competition=competition,
                    commence_time=commence_time,
                    pick=pick,
                    odds=average_odds,
                    probability=statistics.mean(probabilities),
                    bookmaker_count=len(valid_books),
                    consensus_spread=max(probabilities) - min(probabilities),
                    market=market_key,
                )
            )
    return candidates


def format_line(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def selections_from_events(
    events: list[dict[str, Any]],
    sports: dict[str, tuple[str, str]] | None = None,
) -> list[Selection]:
    available_sports = sports or SPORTS
    best_by_event: dict[str, Selection] = {}
    for event in events:
        sport_key = str(event.get("sport_key", ""))
        if sport_key not in available_sports:
            continue
        eligible = quote_candidates(event, sport_key, available_sports)
        if not eligible:
            continue
        best = max(
            eligible,
            key=lambda selection: (
                selection.probability,
                selection.strong_consensus,
                selection.bookmaker_count,
                -selection.odds,
            ),
        )
        if not best.event_id:
            raise ValueError("The Odds API a retourné un match sans identifiant.")
        previous = best_by_event.get(best.event_id)
        if previous is None or best.probability > previous.probability:
            best_by_event[best.event_id] = best
    best_by_fixture: dict[tuple[str, str], Selection] = {}
    for selection in best_by_event.values():
        local_date = selection.commence_time.astimezone(TIMEZONE).date().isoformat()
        key = (local_date, fixture_key(selection.home, selection.away))
        previous = best_by_fixture.get(key)
        if previous is None or selection.probability > previous.probability:
            best_by_fixture[key] = selection
    return sorted(
        best_by_fixture.values(),
        key=lambda selection: (-selection.probability, selection.commence_time),
    )


def average_probability(selections: list[Selection]) -> float:
    if not selections:
        return 0.0
    return statistics.mean(selection.probability for selection in selections)


def choose_panel(panel_choices: list[Panel], max_football: int) -> Panel | None:
    available = [
        panel
        for panel in panel_choices
        if sum(item.sport == "Football" for item in panel.selections) < max_football
    ]
    if not available:
        return None
    return min(
        available,
        key=lambda panel: (
            sum(item.sport == "Football" for item in panel.selections),
            average_probability(panel.selections),
            panel.number,
        ),
    )


def build_panels(selections: list[Selection]) -> list[Panel]:
    panels = [Panel(number=index, selections=[]) for index in (1, 2, 3)]
    football = [item for item in selections if item.sport == "Football"]
    basketball = [
        item
        for item in selections
        if item.sport == "Basketball"
        and item.probability > MIN_BASKETBALL_PROBABILITY
        and item.odds <= 1.32
        and item.strong_consensus
    ]
    used_events: set[str] = set()
    used_matches: set[str] = set()

    for selection in football:
        match = fixture_key(selection.home, selection.away)
        if match in used_matches:
            continue
        panel = choose_panel(panels, max_football=3)
        if panel is None:
            break
        panel.selections.append(selection)
        used_events.add(selection.event_id)
        used_matches.add(match)

    for selection in basketball:
        match = fixture_key(selection.home, selection.away)
        if selection.event_id in used_events or match in used_matches:
            continue
        available = [
            panel
            for panel in panels
            if not any(item.sport == "Basketball" for item in panel.selections)
            and len(panel.selections) < 4
        ]
        if not available:
            break
        panel = min(
            available,
            key=lambda item: (average_probability(item.selections), item.number),
        )
        panel.selections.append(selection)
        used_events.add(selection.event_id)
        used_matches.add(match)

    extra_football = [
        item for item in football if item.event_id not in used_events
    ]
    for selection in extra_football:
        match = fixture_key(selection.home, selection.away)
        if match in used_matches:
            continue
        available = [
            panel
            for panel in panels
            if len(panel.selections) < 4
            and not any(item.sport == "Basketball" for item in panel.selections)
        ]
        if not available:
            break
        panel = min(
            available,
            key=lambda item: (len(item.selections), average_probability(item.selections), item.number),
        )
        panel.selections.append(selection)
        used_events.add(selection.event_id)
        used_matches.add(match)

    for selection in basketball:
        match = fixture_key(selection.home, selection.away)
        if selection.event_id in used_events or match in used_matches:
            continue
        available = [
            panel
            for panel in panels
            if len(panel.selections) < 4
            and sum(item.sport == "Basketball" for item in panel.selections) < 2
        ]
        if not available:
            break
        panel = min(
            available,
            key=lambda item: (len(item.selections), average_probability(item.selections), item.number),
        )
        panel.selections.append(selection)
        used_events.add(selection.event_id)
        used_matches.add(match)

    for panel in panels:
        panel.selections.sort(
            key=lambda selection: (-selection.probability, selection.commence_time)
        )
    return panels


def build_daily_panels(
    selections: list[Selection],
    existing_panels: dict[str, list[list[str]]],
) -> list[Panel]:
    """Assign only new picks to the remaining slots without replacing sheet rows."""
    panels = [Panel(number=index, selections=[]) for index in (1, 2, 3)]
    football_counts = {number: 0 for number in (1, 2, 3)}
    basketball_counts = {number: 0 for number in (1, 2, 3)}
    occupied_counts = {number: 0 for number in (1, 2, 3)}
    existing_matches: set[str] = set()

    for panel in panels:
        rows = existing_panels.get(str(panel.number), [])
        if len(rows) > 4:
            raise RuntimeError(
                f"Le panneau {panel.number} contient déjà plus de 4 matchs."
            )
        for row in rows:
            discipline = normalized(row[3] if len(row) > 3 else "")
            if discipline == normalized("Basketball"):
                basketball_counts[panel.number] += 1
            elif discipline == normalized("Football"):
                football_counts[panel.number] += 1
            else:
                raise RuntimeError(
                    f"Discipline invalide dans le panneau {panel.number}."
                )
            occupied_counts[panel.number] += 1
            if len(row) > 5:
                existing_matches.add(fixture_key_from_match(row[5]))

    if any(
        football_counts[number] > 4 or basketball_counts[number] > 2
        for number in (1, 2, 3)
    ):
        raise RuntimeError("La composition d’un panneau existant ne peut pas être complétée.")

    used_events: set[str] = set()
    used_matches = set(existing_matches)
    candidates = [
        selection
        for selection in selections
        if fixture_key(selection.home, selection.away) not in existing_matches
    ]
    football = [item for item in candidates if item.sport == "Football"]
    basketball = [
        item
        for item in candidates
        if item.sport == "Basketball"
        and item.probability > MIN_BASKETBALL_PROBABILITY
        and item.odds <= 1.32
        and item.strong_consensus
    ]

    def add_next(panel_number: int, choices: list[Selection]) -> bool:
        panel = panels[panel_number - 1]
        for selection in choices:
            match = fixture_key(selection.home, selection.away)
            if selection.event_id in used_events or match in used_matches:
                continue
            panel.selections.append(selection)
            used_events.add(selection.event_id)
            used_matches.add(match)
            occupied_counts[panel_number] += 1
            if selection.sport == "Football":
                football_counts[panel_number] += 1
            else:
                basketball_counts[panel_number] += 1
            return True
        return False

    while True:
        available = [
            panel
            for panel in panels
            if football_counts[panel.number] < 3
            and occupied_counts[panel.number] < 4
        ]
        if not available:
            break
        panel = min(
            available,
            key=lambda item: (football_counts[item.number], item.number),
        )
        if not add_next(panel.number, football):
            break

    for panel in panels:
        number = panel.number
        if (
            football_counts[number] == 3
            and basketball_counts[number] == 0
            and occupied_counts[number] < 4
        ):
            add_next(number, basketball)

    for panel in panels:
        number = panel.number
        while (
            football_counts[number] < (3 if basketball_counts[number] else 4)
            and occupied_counts[number] < 4
            and add_next(number, football)
        ):
            pass

    while True:
        available = [
            panel
            for panel in panels
            if basketball_counts[panel.number] < 2
            and occupied_counts[panel.number] < 4
        ]
        if not available:
            break
        panel = min(
            available,
            key=lambda item: (
                occupied_counts[item.number],
                basketball_counts[item.number],
                item.number,
            ),
        )
        if not add_next(panel.number, basketball):
            break

    for panel in panels:
        panel.selections.sort(
            key=lambda selection: (-selection.probability, selection.commence_time)
        )
    return panels


def format_odds(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def display_panels(panels: list[Panel]) -> None:
    for panel in panels:
        print(
            f"\nPRONOS {panel.number} — {len(panel.selections)} match(s) "
            f"| Cote cumulée : {format_odds(panel.total_odds) if panel.selections else '—'}"
        )
        if not panel.selections:
            print("  Aucune sélection répond aux critères.")
            continue
        for selection in panel.selections:
            local_time = selection.commence_time.astimezone(TIMEZONE)
            print(
                f"  {local_time:%Y-%m-%d %H:%M} — {selection.home} - {selection.away}"
                f" | {selection.pick} @ {format_odds(selection.odds)}"
                f" | probabilité corrigée {selection.probability:.1%}"
                f" | {selection.bookmaker_count} bookmakers"
            )


def panels_to_sheet_rows(panels: list[Panel]) -> list[list[str]]:
    rows = [list(SHEET_HEADERS)]
    for panel in panels:
        by_date: dict[str, list[Selection]] = {}
        for selection in panel.selections:
            match_date = selection.commence_time.astimezone(TIMEZONE)
            by_date.setdefault(match_date.strftime("%Y-%m-%d"), []).append(selection)
        for match_date, day_selections in sorted(by_date.items()):
            total_odds = 1.0
            for selection in day_selections:
                total_odds *= selection.odds
            for selection in day_selections:
                local_time = selection.commence_time.astimezone(TIMEZONE)
                rows.append(
                    [
                        match_date,
                        str(panel.number),
                        "À venir",
                        selection.sport,
                        selection.competition,
                        f"{selection.home} - {selection.away}",
                        selection.pick,
                        format_odds(selection.odds),
                        local_time.strftime("%H:%M"),
                        format_odds(total_odds),
                        "",
                        "",
                    ]
                )
    return rows


def normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in text if not unicodedata.combining(char)).casefold().strip()


def match_key(row: list[str], indexes: dict[str, int]) -> tuple[str, str]:
    match = row[indexes["Match"]] if indexes["Match"] < len(row) else ""
    return (
        row[indexes["Date"]] if indexes["Date"] < len(row) else "",
        fixture_key_from_match(match),
    )


def merge_sheet_rows(
    existing_rows: list[list[str]], new_rows: list[list[str]], now: datetime
) -> list[list[str]]:
    """Keep recent history and append only unlocked, non-duplicate upcoming picks."""
    header = list(SHEET_HEADERS)
    if existing_rows:
        source_header = existing_rows[0]
        source_indexes = {normalized(name): index for index, name in enumerate(source_header)}
    else:
        source_header = header
        source_indexes = {normalized(name): index for index, name in enumerate(header)}

    def normalize_row(row: list[str]) -> list[str]:
        return [
            row[source_indexes.get(normalized(name), -1)]
            if source_indexes.get(normalized(name), -1) >= 0
            and source_indexes[normalized(name)] < len(row)
            else ""
            for name in header
        ]

    old_data = [normalize_row(row) for row in existing_rows[1:] if any(row)]
    cutoff = now.astimezone(TIMEZONE).date() - timedelta(days=10)
    kept_rows = [
        row
        for row in old_data
        if not row[0]
        or not _sheet_date(row[0])
        or _sheet_date(row[0]) >= cutoff
    ]
    indexes = {name: index for index, name in enumerate(header)}
    existing_keys = {match_key(row, indexes) for row in kept_rows}
    panel_rows: dict[tuple[str, str], list[list[str]]] = {}
    locked_panels: set[tuple[str, str]] = set()
    today = now.astimezone(TIMEZONE).date()
    last_generation_date = today + timedelta(days=2)

    for row in kept_rows:
        panel_key = (row[indexes["Date"]], row[indexes["Type de Case"]])
        row_date = _sheet_date(row[indexes["Date"]])
        if row_date and today <= row_date <= last_generation_date:
            panel_rows.setdefault(panel_key, []).append(row)
            status = normalized(row[indexes["Statut global"]])
            has_result = bool(row[indexes["Résultat"]])
            starts_at = _row_start_time(row)
            if (
                status not in {"", normalized("À venir")}
                or has_result
                or (starts_at is not None and starts_at <= now.astimezone(TIMEZONE))
            ):
                locked_panels.add(panel_key)

    complete_dates = {
        match_date
        for match_date, panels in sheet_date_counts([header, *kept_rows]).items()
        if date_is_complete(panels)
    }
    new_indexes = {normalized(name): index for index, name in enumerate(new_rows[0])}
    date_counts: dict[str, int] = {}
    for row in kept_rows:
        date_counts[row[indexes["Date"]]] = date_counts.get(row[indexes["Date"]], 0) + 1
    added_rows = 0
    for raw_row in new_rows[1:]:
        row = normalize_row_from(raw_row, new_indexes)
        date_value = row[indexes["Date"]]
        row_date = _sheet_date(date_value)
        if row_date is None or not today <= row_date <= last_generation_date:
            continue
        if date_value in complete_dates or date_counts.get(date_value, 0) >= 12:
            continue
        key = match_key(row, indexes)
        if not key[1] or key in existing_keys:
            continue
        panel_key = (row[indexes["Date"]], row[indexes["Type de Case"]])
        current_panel_rows = panel_rows.get(panel_key, [])
        if panel_key in locked_panels or len(current_panel_rows) >= 4:
            continue
        kept_rows.append(row)
        panel_rows.setdefault(panel_key, []).append(row)
        existing_keys.add(key)
        date_counts[date_value] = date_counts.get(date_value, 0) + 1
        added_rows += 1

    print(f"Google Sheets : {added_rows} nouveau(x) match(s) ajouté(s), historique conservé.")
    return [header, *kept_rows]


def normalize_row_from(row: list[str], indexes: dict[str, int]) -> list[str]:
    return [
        row[indexes[normalized(name)]]
        if normalized(name) in indexes and indexes[normalized(name)] < len(row)
        else ""
        for name in SHEET_HEADERS
    ]


def _sheet_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _row_start_time(row: list[str]) -> datetime | None:
    match_date = _sheet_date(row[0])
    if match_date is None:
        return None
    try:
        match_time = datetime.strptime(row[8], "%H:%M").time()
    except (IndexError, ValueError):
        return None
    return datetime.combine(match_date, match_time, tzinfo=TIMEZONE)


def google_credentials_ready() -> bool:
    credentials_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    credentials_path = Path("credentials.json")
    if credentials_json:
        try:
            value = json.loads(credentials_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("GOOGLE_CREDENTIALS_JSON n’est pas un JSON valide.") from exc
        if not isinstance(value, dict):
            raise RuntimeError("GOOGLE_CREDENTIALS_JSON doit contenir un objet JSON.")
        return True
    if credentials_path.is_file():
        return True
    raise RuntimeError(
        "Identifiants Google absents : fournissez GOOGLE_CREDENTIALS_JSON "
        "ou placez credentials.json à la racine du dépôt."
    )


def open_google_worksheet():
    try:
        import gspread
    except ImportError as exc:
        raise RuntimeError(
            "gspread n’est pas installé. Lancez : pip install -r requirements.txt"
        ) from exc

    credentials_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    try:
        if credentials_json:
            client = gspread.service_account_from_dict(json.loads(credentials_json))
        else:
            client = gspread.service_account(filename="credentials.json")
        spreadsheet_id = os.environ.get("GOOGLE_SHEET_ID", DEFAULT_SPREADSHEET_ID)
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet_name = os.environ.get("GOOGLE_SHEET_NAME")
        worksheet = (
            spreadsheet.worksheet(worksheet_name)
            if worksheet_name
            else spreadsheet.sheet1
        )
        return worksheet
    except (gspread.exceptions.GSpreadException, OSError, ValueError) as exc:
        raise RuntimeError(f"Accès à Google Sheets impossible : {exc}") from exc


def write_google_sheet(
    rows: list[list[str]],
    now: datetime | None = None,
    worksheet: Any | None = None,
    required_dates: list[date] | None = None,
) -> None:
    worksheet = worksheet or open_google_worksheet()
    old_values = worksheet.get_all_values()
    current_time = now or datetime.now(timezone.utc)
    merged_rows = merge_sheet_rows(old_values, rows, current_time)
    if required_dates:
        grouped = sheet_date_counts(merged_rows)
        incomplete = [
            match_date.isoformat()
            for match_date in required_dates
            if not date_is_complete(grouped.get(match_date.isoformat(), {}))
        ]
        if incomplete:
            source_indexes = {}
            if old_values:
                source_indexes = {
                    normalized(name): index
                    for index, name in enumerate(old_values[0])
                }
            locked_dates: set[str] = set()
            for raw_row in old_values[1:]:
                row = normalize_row_from(raw_row, source_indexes)
                match_date = _sheet_date(row[0])
                if match_date is None or match_date.isoformat() not in incomplete:
                    continue
                status = normalized(row[2])
                starts_at = _row_start_time(row)
                if (
                    status not in {"", normalized("À venir")}
                    or bool(row[10])
                    or (
                        starts_at is not None
                        and starts_at <= current_time.astimezone(TIMEZONE)
                    )
                ):
                    locked_dates.add(match_date.isoformat())
            if locked_dates:
                print(
                    "Information : les dates suivantes restent incomplètes, car les "
                    "matchs déjà enregistrés et verrouillés ne peuvent pas être modifiés : "
                    + ", ".join(sorted(locked_dates))
                )
                return
            else:
                raise RuntimeError(
                    "Les dates suivantes restent incomplètes : "
                    + ", ".join(incomplete)
                )
    old_count = len(old_values)
    row_count = len(merged_rows)
    padded_rows = [
        row + [""] * (len(SHEET_HEADERS) - len(row))
        for row in merged_rows
    ]
    worksheet.update(
        values=padded_rows,
        range_name=f"A1:L{row_count}",
        value_input_option="RAW",
    )
    if old_count > row_count:
        worksheet.batch_clear([f"A{row_count + 1}:L{old_count}"])
    print(
        f"Google Sheets mis à jour : {len(merged_rows) - 1} match(s) conservés, "
        f"onglet « {worksheet.title} »."
    )


def completed_score(event: dict[str, Any], home: str, away: str) -> tuple[int, int] | None:
    scores = event.get("scores")
    if not event.get("completed") or not isinstance(scores, list):
        return None
    by_name = {
        normalized(item.get("name")): item.get("score")
        for item in scores
        if isinstance(item, dict)
    }
    try:
        home_score = int(by_name[normalized(home)])
        away_score = int(by_name[normalized(away)])
    except (KeyError, TypeError, ValueError):
        return None
    return home_score, away_score


def evaluate_pick(pick: str, home_score: int, away_score: int) -> str:
    label = normalized(pick)
    if label in {"vainqueur 1", "victoire domicile", "1"}:
        return "Gagné" if home_score > away_score else "Perdu"
    if label in {"vainqueur 2", "victoire exterieur", "2"}:
        return "Gagné" if away_score > home_score else "Perdu"
    if label in {"match nul", "nul", "x"}:
        return "Gagné" if home_score == away_score else "Perdu"
    if "double chance" in label:
        choice = label.replace("double chance", "").strip()
        if choice in {"1", "1x"}:
            won = home_score >= away_score
        elif choice in {"2", "x2"}:
            won = away_score >= home_score
        elif choice == "12":
            won = home_score != away_score
        else:
            return ""
        return "Gagné" if won else "Perdu"
    total = re.search(r"total\s*([+-])\s*(\d+(?:[,.]\d+)?)", label)
    if total:
        threshold = float(total.group(2).replace(",", "."))
        actual = home_score + away_score
        if actual == threshold:
            return "Remboursé"
        won = actual > threshold if total.group(1) == "+" else actual < threshold
        return "Gagné" if won else "Perdu"
    return ""


def update_sheet_results(api_key: str) -> int:
    worksheet = open_google_worksheet()
    values = worksheet.get_all_values()
    if not values:
        print("Google Sheets ne contient aucune ligne à mettre à jour.")
        return 0
    header = values[0]
    columns = {normalized(name): index for index, name in enumerate(header)}
    required = (
        "discipline", "competition", "match", "prono", "statut global",
        "resultat", "score",
    )
    if any(name not in columns for name in required):
        raise RuntimeError("Colonnes requises pour la mise à jour des résultats introuvables.")
    indexes = {
        "Date": columns.get("date", -1),
        "Type de Case": columns.get("type de case", -1),
        "Statut global": columns["statut global"],
        "Discipline": columns["discipline"],
        "Compétition": columns["competition"],
        "Match": columns["match"],
        "Prono": columns["prono"],
        "Résultat": columns["resultat"],
        "Score": columns["score"],
    }

    def cell(row: list[str], name: str) -> str:
        index = indexes[name]
        return row[index].strip() if index >= 0 and index < len(row) else ""

    if any(
        cell(row, "Compétition")
        and cell(row, "Compétition").casefold() not in SPORT_BY_COMPETITION
        for row in values[1:]
    ):
        active_sports(api_key)

    eligible_sports: set[str] = set()
    for row in values[1:]:
        status = normalized(cell(row, "Statut global"))
        if not cell(row, "Résultat") and status in {"a venir", "en cours", "perdu"}:
            sport_key = SPORT_BY_COMPETITION.get(cell(row, "Compétition").casefold())
            if sport_key:
                eligible_sports.add(sport_key)

    results: dict[str, list[dict[str, Any]]] = {}
    for sport_key in sorted(eligible_sports):
        payload, _ = api_get(
            f"/sports/{sport_key}/scores",
            {"daysFrom": "2", "dateFormat": "iso"},
            api_key,
        )
        if not isinstance(payload, list):
            raise RuntimeError(f"Réponse inattendue de l’API pour {sport_key}/scores.")
        results[sport_key] = [event for event in payload if isinstance(event, dict)]

    changed = 0
    panel_rows: dict[tuple[str, str], list[list[str]]] = {}
    for row in values[1:]:
        if indexes["Date"] >= 0 and indexes["Type de Case"] >= 0:
            panel_rows.setdefault((cell(row, "Date"), cell(row, "Type de Case")), []).append(row)
        if cell(row, "Résultat"):
            continue
        sport_key = SPORT_BY_COMPETITION.get(cell(row, "Compétition").casefold())
        if not sport_key:
            continue
        event = next(
            (
                item for item in results.get(sport_key, [])
                if normalized(item.get("home_team")) == normalized(cell(row, "Match").split(" - ", 1)[0])
                and normalized(item.get("away_team")) == normalized(cell(row, "Match").split(" - ", 1)[-1])
            ),
            None,
        )
        if event is None:
            continue
        teams = completed_score(
            event,
            str(event.get("home_team", "")),
            str(event.get("away_team", "")),
        )
        if teams is None:
            continue
        score = f"{teams[0]} - {teams[1]}"
        result = evaluate_pick(cell(row, "Prono"), *teams)
        if not result:
            continue
        row[indexes["Score"]] = score
        row[indexes["Résultat"]] = result
        changed += 1

    for panel in panel_rows.values():
        states = [cell(row, "Résultat") for row in panel]
        global_status = (
            "Perdu"
            if any(normalized(state) == "perdu" for state in states)
            else "Gagné"
            if states and all(normalized(state) == "gagne" for state in states)
            else "En cours"
            if any(state for state in states)
            else cell(panel[0], "Statut global")
        )
        for row in panel:
            row[indexes["Statut global"]] = global_status

    if changed:
        padded_values = [
            row[: len(SHEET_HEADERS)]
            + [""] * max(0, len(SHEET_HEADERS) - len(row))
            for row in values
        ]
        worksheet.update(
            values=padded_values,
            range_name=f"A1:L{len(values)}",
            value_input_option="RAW",
        )
    print(f"Résultats Google Sheets mis à jour : {changed} match(s).")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Génère les panneaux Goal4win depuis The Odds API."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="affiche les panneaux sans modifier Google Sheets",
    )
    parser.add_argument(
        "--update-results",
        action="store_true",
        help="met à jour les scores/résultats des matchs déjà publiés",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ODDS_API_KEY")
    if args.update_results:
        if args.dry_run:
            parser.error("--dry-run ne peut pas être combiné avec --update-results.")
        if not api_key:
            parser.error("la variable d’environnement ODDS_API_KEY est obligatoire.")
        google_credentials_ready()
        update_sheet_results(api_key)
        return 0
    if not api_key:
        parser.error("la variable d’environnement ODDS_API_KEY est obligatoire.")
    if not args.dry_run:
        google_credentials_ready()

    now = datetime.now(timezone.utc)
    today = now.astimezone(TIMEZONE).date()
    target_dates = [today + timedelta(days=offset) for offset in range(3)]
    worksheet = None
    existing_rows: list[list[str]] = []
    if not args.dry_run:
        worksheet = open_google_worksheet()
        existing_rows = worksheet.get_all_values()

    existing_by_date = sheet_date_counts(existing_rows)
    missing_dates = [
        match_date
        for match_date in target_dates
        if match_date.isoformat() not in existing_by_date
    ]
    for match_date in target_dates:
        existing_for_date = existing_by_date.get(match_date.isoformat(), {})
        if existing_for_date and not date_is_complete(existing_for_date):
            print(
                f"Information : le {match_date.isoformat()} est déjà présent "
                "dans Google Sheets ; aucun appel API ni modification."
            )
    panels_by_date: dict[date, list[Panel]] = {}
    remaining: list[str] = []
    odds_requests = 0
    if missing_dates:
        sports = active_sports(api_key)
        panels_by_date, remaining, odds_requests = fetch_daily_panels(
            api_key, missing_dates, now, sports, existing_rows
        )

    for match_date, panels in panels_by_date.items():
        print(f"\nPronostics du {match_date.isoformat()} (heure du Cameroun) :")
        display_panels(panels)
    print(
        f"Crédits Odds API estimés pour les cotes : "
        f"{odds_requests * len(MARKETS)} "
        f"({odds_requests} requête(s) de cotes, région eu)."
    )
    if remaining:
        print(f"Crédits restants selon l’API : {remaining[-1]}.")
    if args.dry_run:
        print("\nMode dry-run : Google Sheets n’a pas été modifié.")
    elif panels_by_date:
        rows = [list(SHEET_HEADERS)]
        for panels in panels_by_date.values():
            rows.extend(panels_to_sheet_rows(panels)[1:])
        write_google_sheet(rows, now, worksheet, list(panels_by_date))
    elif missing_dates:
        print("\nAucun pronostic généré ; Google Sheets n’a pas été modifié.")
    else:
        print("\nLes dates J, J+1 et J+2 sont déjà présentes ; aucune modification.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
