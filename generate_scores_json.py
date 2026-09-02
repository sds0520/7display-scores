#!/usr/bin/env python3
"""
generate_scores_json.py
------------------------------------------------------------------
Builds scores.json for the 7Display kitchen board's Scores screen.

Reads scores_input.json and writes scores.json.

Output for each in-season sport:
  - last: short last-result line for the Scores card
  - next: short next-event line for the Scores card
  - recap: longer text-only recap for tapping Last
  - schedule: up to the next 10 events for tapping Next

Usage:
  python3 generate_scores_json.py --input scores_input.json --out scores.json
"""

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
MAX_SCHEDULE_ITEMS = 10

SEASON_WINDOWS = {
    "mlb":    (4, 11),
    "nfl":    (8, 2),
    "ncaam":  (12, 4),
    "ncaaw":  (12, 4),
    "nascar": (2, 11),
}

SPORT_META = {
    "mlb":    {"title": "MLB"},
    "nfl":    {"title": "NFL"},
    "ncaam":  {"title": "NCAA (M)"},
    "ncaaw":  {"title": "NCAAW"},
    "nascar": {"title": "NASCAR"},
}


def in_season(key: str, month: int) -> bool:
    start, end = SEASON_WINDOWS[key]
    if start <= end:
        return start <= month <= end
    return month >= start or month <= end


def fmt_date_short(iso_str):
    """'2026-09-02' or full ISO -> 'Sep 2'."""
    if not iso_str:
        return ""

    try:
        d = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        if d.tzinfo is not None:
            d = d.astimezone(TZ)
        return d.strftime("%b %-d")
    except Exception:
        try:
            d = datetime.strptime(str(iso_str)[:10], "%Y-%m-%d")
            return d.strftime("%b %-d")
        except Exception:
            return str(iso_str)[:10]


def fmt_datetime_short(iso_str):
    """Full ISO -> 'Sep 13, 1:00 PM' in America/New_York."""
    if not iso_str:
        return ""

    try:
        d = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        if d.tzinfo is not None:
            d = d.astimezone(TZ)
        return d.strftime("%b %-d, %-I:%M %p")
    except Exception:
        return fmt_date_short(iso_str)


def safe_text(value):
    """Return a clean string without displaying None."""
    if value is None:
        return ""
    return str(value).strip()


def sentence(text):
    """Make supplied text safe to add as a sentence."""
    text = safe_text(text)
    if not text:
        return ""
    if text[-1] not in ".!?":
        text += "."
    return text


def format_team_last(entry):
    """entry: {is_home, team_score, opp_score, opponent, date}"""
    if not entry:
        return "No result yet"

    try:
        team_score = int(entry["team_score"])
        opp_score = int(entry["opp_score"])
    except (KeyError, TypeError, ValueError):
        return "No result yet"

    opponent = safe_text(entry.get("opponent")) or "opponent"
    is_home = bool(entry.get("is_home"))
    outcome = "W" if team_score > opp_score else ("L" if team_score < opp_score else "T")
    versus = "vs" if is_home else "@"
    date_str = fmt_date_short(entry.get("date"))

    line = f"{outcome} {team_score}-{opp_score} {versus} {opponent}"
    if date_str:
        line += f" ({date_str})"
    return line


def format_team_next(entry):
    """entry: {is_home, opponent, date}"""
    if not entry:
        return "Not yet scheduled"

    opponent = safe_text(entry.get("opponent")) or "opponent"
    is_home = bool(entry.get("is_home"))
    versus = "vs" if is_home else "@"
    date_str = fmt_datetime_short(entry.get("date"))

    line = f"{versus} {opponent}"
    if date_str:
        line += f" - {date_str}"
    return line


def format_race_last(entry):
    """entry: {name, date, venue, winner}"""
    if not entry:
        return "No result yet"

    name = safe_text(entry.get("name")) or "Race"
    date_str = fmt_date_short(entry.get("date"))
    winner = safe_text(entry.get("winner"))

    line = name
    if date_str:
        line += f" ({date_str})"
    if winner:
        line += f" - Winner: {winner}"
    return line


def format_race_next(entry):
    """entry: {name, date, venue}"""
    if not entry:
        return "Not yet scheduled"

    name = safe_text(entry.get("name")) or "Race"
    venue = safe_text(entry.get("venue"))
    date_str = fmt_datetime_short(entry.get("date"))

    line = name
    if venue:
        line += f" - {venue}"
    if date_str:
        line += f" - {date_str}"
    return line


def team_recap(key, data, last_entry):
    """Build a readable recap from available team-game fields."""
    if not last_entry:
        return "No completed game result is available yet."

    result_line = format_team_last(last_entry)
    team_name = safe_text(data.get("team_label")) or SPORT_META[key]["title"]
    opponent = safe_text(last_entry.get("opponent")) or "the opponent"
    is_home = bool(last_entry.get("is_home"))
    location = "at home against" if is_home else "on the road against"

    pieces = [f"{team_name} last played {location} {opponent}. The result was {result_line}."]

    detail_fields = (
        "recap",
        "summary",
        "game_recap",
        "details",
        "description",
    )

    for field in detail_fields:
        detail = safe_text(last_entry.get(field)) or safe_text(data.get(field))
        if detail:
            pieces.append(sentence(detail))
            break

    highlights = safe_text(last_entry.get("highlights")) or safe_text(data.get("highlights"))
    if highlights:
        pieces.append(sentence(highlights))

    stats = safe_text(last_entry.get("stats")) or safe_text(data.get("stats"))
    if stats:
        pieces.append(sentence(stats))

    record = safe_text(last_entry.get("record")) or safe_text(data.get("record"))
    if record:
        pieces.append(f"Current record: {record}.")

    next_game = format_team_next(data.get("next"))
    if next_game and next_game != "Not yet scheduled":
        pieces.append(f"Next: {next_game}.")

    return " ".join(pieces)


def nascar_recap(data, last_entry):
    """Build a readable race recap from available NASCAR fields."""
    if not last_entry:
        return "No completed NASCAR Cup Series race result is available yet."

    race_name = safe_text(last_entry.get("name")) or "The most recent race"
    venue = safe_text(last_entry.get("venue"))
    winner = safe_text(last_entry.get("winner"))
    date_str = fmt_date_short(last_entry.get("date"))

    first = race_name
    if venue:
        first += f" at {venue}"
    if date_str:
        first += f" on {date_str}"
    first += "."

    pieces = [first]

    if winner:
        pieces.append(f"The winner was {winner}.")

    detail_fields = (
        "recap",
        "summary",
        "race_recap",
        "details",
        "description",
    )

    for field in detail_fields:
        detail = safe_text(last_entry.get(field)) or safe_text(data.get(field))
        if detail:
            pieces.append(sentence(detail))
            break

    highlights = safe_text(last_entry.get("highlights")) or safe_text(data.get("highlights"))
    if highlights:
        pieces.append(sentence(highlights))

    standings = safe_text(last_entry.get("standings")) or safe_text(data.get("standings"))
    if standings:
        pieces.append(sentence(standings))

    next_race = format_race_next(data.get("next"))
    if next_race and next_race != "Not yet scheduled":
        pieces.append(f"Next: {next_race}.")

    return " ".join(pieces)


def format_team_schedule_entry(entry):
    """Format one upcoming MLB/NFL/NCAA event."""
    if not entry:
        return ""

    opponent = safe_text(entry.get("opponent")) or "Opponent TBD"
    is_home = bool(entry.get("is_home"))
    versus = "vs" if is_home else "@"
    date_str = fmt_datetime_short(entry.get("date"))

    line = f"{versus} {opponent}"
    if date_str:
        line += f" - {date_str}"

    network = safe_text(entry.get("network"))
    if network:
        line += f" ({network})"

    return line


def format_race_schedule_entry(entry):
    """Format one upcoming NASCAR event."""
    if not entry:
        return ""

    name = safe_text(entry.get("name")) or "Race"
    venue = safe_text(entry.get("venue"))
    date_str = fmt_datetime_short(entry.get("date"))

    line = name
    if venue:
        line += f" - {venue}"
    if date_str:
        line += f" - {date_str}"

    network = safe_text(entry.get("network"))
    if network:
        line += f" ({network})"

    return line


def get_future_events(data):
    """
    Accept several possible input names, so existing source data does not
    have to use one exact key name.
    """
    for field in ("schedule", "upcoming", "upcoming_events", "future_events", "next_events"):
        items = data.get(field)
        if isinstance(items, list) and items:
            return items
    return []


def build_schedule(key, data):
    """Build exactly up to 10 display-ready future event lines."""
    events = get_future_events(data)

    if not events:
        next_event = data.get("next")
        if next_event:
            events = [next_event]

    lines = []

    for event in events:
        if key == "nascar":
            line = format_race_schedule_entry(event)
        else:
            line = format_team_schedule_entry(event)

        if line and line not in lines:
            lines.append(line)

        if len(lines) >= MAX_SCHEDULE_ITEMS:
            break

    if not lines:
        lines.append("No upcoming events are available yet.")

    return lines


def build_card(key, data):
    meta = SPORT_META[key]
    label = safe_text(data.get("team_label")) or meta["title"]
    title = meta["title"] if label == meta["title"] else f"{meta['title']} - {label}"

    last_entry = data.get("last") or {}
    next_entry = data.get("next") or {}

    if key == "nascar":
        last_line = format_race_last(last_entry)
        next_line = format_race_next(next_entry)
        recap = nascar_recap(data, last_entry)
    else:
        last_line = format_team_last(last_entry)
        next_line = format_team_next(next_entry)
        recap = team_recap(key, data, last_entry)

    return {
        "key": key,
        "title": title,
        "last": last_line,
        "next": next_line,
        "recap": recap,
        "schedule": build_schedule(key, data),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="scores_input.json")
    parser.add_argument("--out", default="scores.json")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        raw = json.load(f)

    now = datetime.now(TZ)
    cards = []

    for key in ("mlb", "nfl", "ncaam", "ncaaw", "nascar"):
        if not in_season(key, now.month):
            continue

        data = raw.get(key) or {}
        cards.append(build_card(key, data))

    out = {
        "generated_at": now.isoformat(),
        "cards": cards,
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(
        f"Wrote {args.out} with {len(cards)} in-season card(s): "
        f"{[card['key'] for card in cards]}"
    )


if __name__ == "__main__":
    main()
