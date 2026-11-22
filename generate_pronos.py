#!/usr/bin/env python3
"""Generate objective Goal4win selections from The Odds API."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo


API_BASE = "https://api.the-odds-api.com/v4"
TIMEZONE = ZoneInfo("Europe/Paris")
MARKETS = ("h2h", "totals")
MIN_ODDS = 1.20
MAX_ODDS = 1.50
MIN_BOOKMAKERS = 3
MAX_BASKETBALL_ODDS = 1.32
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
    "soccer_france_ligue_one": ("Football", "Ligue 1"),
    "soccer_uefa_champs_league": ("Football", "Ligue des champions"),
    "soccer_uefa_europa_league": ("Football", "Ligue Europa"),
    "basketball_nba": ("Basketball", "NBA"),
    "basketball_euroleague": ("Basketball", "EuroLeague"),
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
    try:
        with urlopen(request_url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
            headers = {key.lower(): value for key, value in response.headers.items()}
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"The Odds API a renvoyé HTTP {exc.code} pour {path}: "
            f"{message or exc.reason}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Connexion à The Odds API impossible : {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Réponse JSON invalide de The Odds API ({path}).") from exc
    return payload, headers


def fetch_events(
    api_key: str, start: datetime, end: datetime
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Use the free events endpoint first, so inactive leagues cost no odds credits."""
    events: list[dict[str, Any]] = []
    remaining: list[str] = []
    odds_requests = 0
    for sport_key in SPORTS:
        params = {
            "dateFormat": "iso",
            "commenceTimeFrom": iso_utc(start),
            "commenceTimeTo": iso_utc(end),
        }
        payload, _ = api_get(f"/sports/{sport_key}/events", params, api_key)
        if not isinstance(payload, list):
            raise RuntimeError(f"Réponse inattendue de l’API pour {sport_key}/events.")
        if not payload:
            print(f"{sport_key}: aucun match dans les prochaines 24 h.")
            continue

        odds_params = {
            **params,
            "regions": "eu",
            "markets": ",".join(MARKETS),
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
        odds_payload, headers = api_get(
            f"/sports/{sport_key}/odds", odds_params, api_key
        )
        odds_requests += 1
        if not isinstance(odds_payload, list):
            raise RuntimeError(f"Réponse inattendue de l’API pour {sport_key}/odds.")
        if headers.get("x-requests-remaining") is not None:
            remaining.append(headers["x-requests-remaining"])
        events.extend(
            event
            for event in odds_payload
            if is_in_window(event.get("commence_time"), start, end)
        )
        print(f"{sport_key}: {len(odds_payload)} match(s) avec cotes récupérés.")
    return events, remaining, odds_requests


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


def quote_candidates(event: dict[str, Any], sport_key: str) -> list[Selection]:
    try:
        commence_time = parse_datetime(str(event["commence_time"]))
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Match sans heure de début valide : {event!r}") from exc
    sport, competition = SPORTS[sport_key]
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
            quotes = [prices[key] for prices in valid_books]
            average_odds = statistics.mean(quotes)
            if not MIN_ODDS < average_odds < MAX_ODDS:
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


def selections_from_events(events: list[dict[str, Any]]) -> list[Selection]:
    best_by_event: dict[str, Selection] = {}
    for event in events:
        sport_key = str(event.get("sport_key", ""))
        if sport_key not in SPORTS:
            continue
        eligible = quote_candidates(event, sport_key)
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
    return sorted(
        best_by_event.values(),
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
        and (item.odds <= MAX_BASKETBALL_ODDS or (
            item.probability > 0.75 and item.strong_consensus
        ))
    ]
    used_events: set[str] = set()

    for selection in football:
        panel = choose_panel(panels, max_football=3)
        if panel is None:
            break
        panel.selections.append(selection)
        used_events.add(selection.event_id)

    for selection in basketball:
        if selection.event_id in used_events:
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

    extra_football = [
        item for item in football if item.event_id not in used_events
    ]
    for selection in extra_football:
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


def write_google_sheet(rows: list[list[str]]) -> None:
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
        old_rows = len(worksheet.get_all_values())
        row_count = max(old_rows, len(rows))
        padded_rows = rows + [[""] * len(SHEET_HEADERS) for _ in range(row_count - len(rows))]
        worksheet.update(
            values=padded_rows,
            range_name=f"A1:L{row_count}",
            value_input_option="RAW",
        )
    except (gspread.exceptions.GSpreadException, OSError, ValueError) as exc:
        raise RuntimeError(f"Écriture Google Sheets impossible : {exc}") from exc
    print(
        f"Google Sheets mis à jour : {len(rows) - 1} match(s), "
        f"onglet « {worksheet.title} »."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Génère les panneaux Goal4win depuis The Odds API."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="affiche les panneaux sans modifier Google Sheets",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        parser.error("la variable d’environnement ODDS_API_KEY est obligatoire.")
    if not args.dry_run:
        google_credentials_ready()

    now = datetime.now(timezone.utc)
    start, end = now, now + timedelta(hours=24)
    events, remaining, odds_requests = fetch_events(api_key, start, end)
    selections = selections_from_events(events)
    panels = build_panels(selections)

    print(
        f"\n{len(events)} match(s) reçus dans la fenêtre "
        f"{start.astimezone(TIMEZONE):%Y-%m-%d %H:%M}–"
        f"{end.astimezone(TIMEZONE):%Y-%m-%d %H:%M} (heure de Paris)."
    )
    print(
        f"Crédits Odds API estimés pour les cotes : "
        f"{odds_requests * len(MARKETS)} "
        f"({odds_requests} requête(s) de cotes, région eu)."
    )
    if remaining:
        print(f"Crédits restants selon l’API : {remaining[-1]}.")
    display_panels(panels)
    if args.dry_run:
        print("\nMode dry-run : Google Sheets n’a pas été modifié.")
    else:
        write_google_sheet(panels_to_sheet_rows(panels))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
