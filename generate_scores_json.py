#!/usr/bin/env python3
"""
generate_scores_json.py
------------------------------------------------------------------
Builds scores.json for the 7Display kitchen board's Scores screen.

Reads a normalized input file (scores_input.json) that a scheduled
Computer task fills in each run with the latest data for each sport
(pulled from the OpticOdds connector for MLB/NFL/NCAAM/NCAAW and from
TheSportsDB + a web search for the race winner for NASCAR).

This script's only two jobs:
  1. Decide which sports are "in season" right now (America/New_York),
     using the exact month windows the user specified:
       MLB     : April - November
       NFL     : August - February  (wraps the calendar year)
       NCAAM/W : December - April
       NASCAR  : February - November
  2. Format each in-season sport's last result + next event into short,
     device-ready strings, and write scores.json with ONLY the in-season
     entries (out-of-season sports are omitted entirely to save space
     on the 800x480 panel, per the user's request).

Usage:
  python3 generate_scores_json.py --input scores_input.json --out scores.json
"""

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")

# (label, start_month, end_month) - end_month < start_month means the
# window wraps across the new year (e.g. NFL: Aug(8) -> Feb(2)).
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
    # Wraps the year boundary (e.g. 8..2 means Aug,Sep,...,Dec,Jan,Feb)
    return month >= start or month <= end


def fmt_date_short(iso_str):
    """'2026-09-02' or full ISO -> 'Sep 2'. Returns '' if unparseable."""
    if not iso_str:
        return ""
    try:
        d = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if d.tzinfo is not None:
            d = d.astimezone(TZ)
        return d.strftime("%b %-d")
    except Exception:
        try:
            d = datetime.strptime(iso_str[:10], "%Y-%m-%d")
            return d.strftime("%b %-d")
        except Exception:
            return iso_str[:10]


def fmt_datetime_short(iso_str):
    """Full ISO -> 'Sep 13, 1:00 PM' (America/New_York). '' if unparseable."""
    if not iso_str:
        return ""
    try:
        d = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if d.tzinfo is not None:
            d = d.astimezone(TZ)
        return d.strftime("%b %-d, %-I:%M %p")
    except Exception:
        return fmt_date_short(iso_str)


def format_team_last(entry):
    """entry: {is_home, team_score, opp_score, opponent, date}"""
    if not entry:
        return "No result yet"
    try:
        team_score = int(entry["team_score"])
        opp_score = int(entry["opp_score"])
    except (KeyError, TypeError, ValueError):
        return "No result yet"
    opponent = entry.get("opponent", "")
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
    opponent = entry.get("opponent", "")
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
    name = entry.get("name", "Race")
    date_str = fmt_date_short(entry.get("date"))
    winner = entry.get("winner")
    line = name
    if date_str:
        line += f" ({date_str})"
    if winner:
        line += f" - Winner: {winner}"
    return line


def format_race_next(entry):
    """entry: {name, date, venue}. Uses a date-only format since exact
    green-flag times aren't reliably available from the free race feed."""
    if not entry:
        return "Not yet scheduled"
    name = entry.get("name", "Race")
    venue = entry.get("venue")
    date_str = fmt_date_short(entry.get("date"))
    line = name
    if venue:
        line += f" - {venue}"
    if date_str:
        line += f" ({date_str})"
    return line


def build_card(key, data):
    meta = SPORT_META[key]
    label = data.get("team_label") or meta["title"]
    title = meta["title"] if label == meta["title"] else f"{meta['title']} - {label}"

    if key == "nascar":
        last_line = format_race_last(data.get("last"))
        next_line = format_race_next(data.get("next"))
    else:
        last_line = format_team_last(data.get("last"))
        next_line = format_team_next(data.get("next"))

    return {
        "key": key,
        "title": title,
        "last": last_line,
        "next": next_line,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="scores_input.json")
    parser.add_argument("--out", default="scores.json")
    args = parser.parse_args()

    with open(args.input, "r") as f:
        raw = json.load(f)

    now = datetime.now(TZ)
    month = now.month

    cards = []
    for key in ("mlb", "nfl", "ncaam", "ncaaw", "nascar"):
        if not in_season(key, month):
            continue
        data = raw.get(key) or {}
        cards.append(build_card(key, data))

    out = {
        "generated_at": now.isoformat(),
        "cards": cards,
    }

    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)

    print(f"Wrote {args.out} with {len(cards)} in-season card(s): "
          f"{[c['key'] for c in cards]}")


if __name__ == "__main__":
    main()
