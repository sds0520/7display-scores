#!/usr/bin/env python3
import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
MAX_SCHEDULE_ITEMS = 12

SEASON_WINDOWS = {
    "mlb":    (4, 11),
    "nfl":    (8, 2),
    "ncaam":  (12, 4),
    "ncaaw":  (11, 4),
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


def safe_text(value):
    if value is None:
        return ""
    return str(value).strip()


def sentence(text):
    text = safe_text(text)
    if not text:
        return ""
    if text[-1] not in ".!?":
        text += "."
    return text


def fmt_date_short(iso_str):
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
    if not iso_str:
        return ""
    try:
        d = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        if d.tzinfo is not None:
            d = d.astimezone(TZ)
        return d.strftime("%b %-d, %-I:%M %p")
    except Exception:
        return fmt_date_short(iso_str)


def join_names(items):
    clean = [safe_text(x) for x in (items or []) if safe_text(x)]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} and {clean[1]}"
    return ", ".join(clean[:-1]) + f", and {clean[-1]}"


def format_team_last(entry):
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


def mlb_recap(data, last_entry):
    if not last_entry:
        return "No completed game result is available yet."
    team_name = safe_text(data.get("team_label")) or "MLB"
    opponent = safe_text(last_entry.get("opponent")) or "the opponent"
    result_line = format_team_last(last_entry)
    is_home = bool(last_entry.get("is_home"))
    location = "at home against" if is_home else "on the road against"
    pieces = [f"{team_name} last played {location} {opponent}. The result was {result_line}."]

    wp = safe_text(last_entry.get("winning_pitcher"))
    lp = safe_text(last_entry.get("losing_pitcher"))
    sv = safe_text(last_entry.get("save_pitcher"))
    if wp or lp or sv:
        pitching = []
        if wp:
            pitching.append(f"Winning pitcher: {wp}")
        if lp:
            pitching.append(f"Losing pitcher: {lp}")
        if sv:
            pitching.append(f"Save: {sv}")
        pieces.append(sentence(". ".join(pitching)))

    hr_hitters = last_entry.get("home_run_hitters") or last_entry.get("home_runs") or []
    hr_text = join_names(hr_hitters)
    if hr_text:
        pieces.append(f"Yankees home runs: {hr_text}.")

    detail = safe_text(last_entry.get("recap") or last_entry.get("summary") or last_entry.get("game_recap") or data.get("recap"))
    if detail:
        pieces.append(sentence(detail))

    highlights = safe_text(last_entry.get("highlights") or data.get("highlights"))
    if highlights:
        pieces.append(sentence(highlights))

    record = safe_text(last_entry.get("record") or data.get("record"))
    if record:
        pieces.append(f"Current record: {record}.")

    next_game = format_team_next(data.get("next"))
    if next_game and next_game != "Not yet scheduled":
        pieces.append(f"Next: {next_game}.")
    return " ".join(pieces)


def nfl_recap(data, last_entry):
    if not last_entry:
        return "No completed game result is available yet."
    team_name = safe_text(data.get("team_label")) or "NFL"
    opponent = safe_text(last_entry.get("opponent")) or "the opponent"
    result_line = format_team_last(last_entry)
    is_home = bool(last_entry.get("is_home"))
    location = "at home against" if is_home else "on the road against"
    pieces = [f"{team_name} last played {location} {opponent}. The result was {result_line}."]

    qb = last_entry.get("qb") or {}
    qb_name = safe_text(qb.get("name"))
    qb_stats = safe_text(qb.get("stats"))
    if qb_name or qb_stats:
        pieces.append(sentence(f"Steelers QB: {qb_name} {qb_stats}".strip()))

    rb = last_entry.get("top_rb") or {}
    rb_name = safe_text(rb.get("name"))
    rb_stats = safe_text(rb.get("stats"))
    if rb_name or rb_stats:
        pieces.append(sentence(f"Top RB: {rb_name} {rb_stats}".strip()))

    wr = last_entry.get("top_wr") or {}
    wr_name = safe_text(wr.get("name"))
    wr_stats = safe_text(wr.get("stats"))
    if wr_name or wr_stats:
        pieces.append(sentence(f"Top WR: {wr_name} {wr_stats}".strip()))

    turnovers = last_entry.get("turnovers") or {}
    team_to = safe_text(turnovers.get("team"))
    opp_to = safe_text(turnovers.get("opponent"))
    if team_to or opp_to:
        pieces.append(f"Turnovers: Steelers {team_to or '0'}, {opponent} {opp_to or '0'}.")

    detail = safe_text(last_entry.get("recap") or last_entry.get("summary") or last_entry.get("game_recap") or data.get("recap"))
    if detail:
        pieces.append(sentence(detail))

    record = safe_text(last_entry.get("record") or data.get("record"))
    if record:
        pieces.append(f"Current record: {record}.")

    next_game = format_team_next(data.get("next"))
    if next_game and next_game != "Not yet scheduled":
        pieces.append(f"Next: {next_game}.")
    return " ".join(pieces)


def ncaa_recap(key, data, last_entry):
    if not last_entry:
        return "No completed game result is available yet."
    team_name = safe_text(data.get("team_label")) or SPORT_META[key]["title"]
    opponent = safe_text(last_entry.get("opponent")) or "the opponent"
    result_line = format_team_last(last_entry)
    is_home = bool(last_entry.get("is_home"))
    location = "at home against" if is_home else "on the road against"
    pieces = [f"{team_name} last played {location} {opponent}. The result was {result_line}."]

    leaders = last_entry.get("leaders") or {}
    pts = leaders.get("points") or {}
    reb = leaders.get("rebounds") or {}
    ast = leaders.get("assists") or {}
    if pts:
        pieces.append(sentence(f"Top scorer: {safe_text(pts.get('name'))} with {safe_text(pts.get('value'))} points"))
    if reb:
        pieces.append(sentence(f"Top rebounder: {safe_text(reb.get('name'))} with {safe_text(reb.get('value'))} rebounds"))
    if ast:
        pieces.append(sentence(f"Top assist leader: {safe_text(ast.get('name'))} with {safe_text(ast.get('value'))} assists"))

    team_pct = last_entry.get("team_pct") or {}
    ft = safe_text(team_pct.get("ft"))
    fg = safe_text(team_pct.get("fg"))
    tp = safe_text(team_pct.get("three"))
    pct_parts = []
    if ft:
        pct_parts.append(f"free throws {ft}")
    if fg:
        pct_parts.append(f"field goals {fg}")
    if tp:
        pct_parts.append(f"three-pointers {tp}")
    if pct_parts:
        pieces.append(sentence("Team shooting: " + ", ".join(pct_parts)))

    detail = safe_text(last_entry.get("recap") or last_entry.get("summary") or last_entry.get("game_recap") or data.get("recap"))
    if detail:
        pieces.append(sentence(detail))

    record = safe_text(last_entry.get("record") or data.get("record"))
    if record:
        pieces.append(f"Current record: {record}.")

    next_game = format_team_next(data.get("next"))
    if next_game and next_game != "Not yet scheduled":
        pieces.append(f"Next: {next_game}.")
    return " ".join(pieces)


def nascar_recap(data, last_entry):
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
    detail = safe_text(last_entry.get("recap") or last_entry.get("summary") or last_entry.get("race_recap") or data.get("recap"))
    if detail:
        pieces.append(sentence(detail))
    highlights = safe_text(last_entry.get("highlights") or data.get("highlights"))
    if highlights:
        pieces.append(sentence(highlights))
    next_race = format_race_next(data.get("next"))
    if next_race and next_race != "Not yet scheduled":
        pieces.append(f"Next: {next_race}.")
    return " ".join(pieces)


def format_team_schedule_entry(entry):
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
    for field in ("schedule", "upcoming", "upcoming_events", "future_events", "next_events"):
        items = data.get(field)
        if isinstance(items, list) and items:
            return items
    return []


def build_schedule(key, data):
    events = get_future_events(data)
    if not events:
        next_event = data.get("next")
        if next_event:
            events = [next_event]
    lines = []
    for event in events:
        line = format_race_schedule_entry(event) if key == "nascar" else format_team_schedule_entry(event)
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
        if key == "mlb":
            recap = mlb_recap(data, last_entry)
        elif key == "nfl":
            recap = nfl_recap(data, last_entry)
        elif key in ("ncaam", "ncaaw"):
            recap = ncaa_recap(key, data, last_entry)
        else:
            recap = sentence(safe_text(last_entry.get("recap") or data.get("recap"))) or "No recap available."

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
    parser.add_argument("--include-empty-in-season", action="store_true")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        raw = json.load(f)

    now = datetime.now(TZ)
    cards = []
    for key in ("mlb", "nfl", "ncaam", "ncaaw", "nascar"):
        if not in_season(key, now.month):
            continue
        data = raw.get(key) or {}
        if not args.include_empty_in_season and not (data.get("last") or data.get("next") or get_future_events(data)):
            continue
        cards.append(build_card(key, data))

    out = {"generated_at": now.isoformat(), "cards": cards}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()
