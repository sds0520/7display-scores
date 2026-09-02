#!/usr/bin/env python3
"""
generate_scores_json.py
------------------------------------------------------------------
Builds scores.json for the 7Display kitchen board's Scores screen.

Reads scores_input.json (written by collect_scores_input.py) and
writes the flattened scores.json that the ESP32 downloads.

The device stays simple on purpose: it renders whatever text this
script produces. All formatting, season filtering, and stat
assembly happens here, not on the microcontroller.

Output per in-season sport:
  last     - short last-result line for the card
  next     - short next-event line for the card
  recap    - detailed text-only recap shown when Last is tapped
  schedule - up to 12 upcoming events shown when Next is tapped
  columns  - optional structured grid (NASCAR points standings)

Usage:
  python3 generate_scores_json.py --input scores_input.json --out scores.json
"""

import argparse
import json
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
MAX_SCHEDULE_ITEMS = 12

# Month windows, inclusive, wrapping across the new year where needed.
#
# NOTE ON COLLEGE BASKETBALL: Dec-Apr is intentional. UConn plays in
# November, but those early-season games are deliberately not shown -
# the college cards appear in December.
SEASON_WINDOWS = {
    "mlb":    (3, 11),
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

NASCAR_STANDINGS_COLUMNS = 2


# ----------------------------------------------------------- small helpers

# The LVGL Montserrat fonts built into the sketch cover ASCII only, so
# anything else (Suarez, Bichette, Jokic...) would render as blank boxes
# on the panel. Fold to ASCII on the way out; scores_input.json keeps the
# correct spelling.
ASCII_FALLBACKS = {
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2026": "...", "\u00a0": " ",
    "\u00d8": "O", "\u00f8": "o", "\u00c6": "AE", "\u00e6": "ae",
    "\u0110": "D", "\u0111": "d", "\u00df": "ss", "\u0141": "L",
    "\u0142": "l",
}


def to_ascii(value):
    for src, dst in ASCII_FALLBACKS.items():
        value = value.replace(src, dst)
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.encode("ascii", "ignore").decode("ascii")


def asciify(node):
    """Recursively ASCII-fold every string in the outgoing feed."""
    if isinstance(node, str):
        return to_ascii(node)
    if isinstance(node, list):
        return [asciify(v) for v in node]
    if isinstance(node, dict):
        return {k: asciify(v) for k, v in node.items()}
    return node


def in_season(key, month):
    start, end = SEASON_WINDOWS[key]
    if start <= end:
        return start <= month <= end
    return month >= start or month <= end


def txt(value):
    return "" if value is None else str(value).strip()


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
            return datetime.strptime(str(iso_str)[:10], "%Y-%m-%d").strftime("%b %-d")
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


def short_team(name):
    """'Los Angeles Angels' -> 'Angels' so card lines stay narrow."""
    name = txt(name)
    if not name:
        return "TBD"
    parts = name.split()
    return parts[-1] if len(parts) > 1 else name


def outcome_letter(ours, theirs):
    if ours is None or theirs is None:
        return "?"
    if ours > theirs:
        return "W"
    if ours < theirs:
        return "L"
    return "T"


# ------------------------------------------------------------- card lines

def format_team_last(entry):
    if not entry:
        return "No result yet"
    ours, theirs = entry.get("team_score"), entry.get("opp_score")
    if ours is None or theirs is None:
        return "No result yet"
    versus = "vs" if entry.get("is_home") else "@"
    line = f"{outcome_letter(ours, theirs)} {ours}-{theirs} {versus} {short_team(entry.get('opponent'))}"
    date_str = fmt_date_short(entry.get("date"))
    return f"{line} ({date_str})" if date_str else line


def format_team_next(entry):
    if not entry:
        return "Not yet scheduled"
    versus = "vs" if entry.get("is_home") else "@"
    line = f"{versus} {short_team(entry.get('opponent'))}"
    date_str = fmt_datetime_short(entry.get("date"))
    return f"{line} - {date_str}" if date_str else line


def format_race_last(entry):
    if not entry:
        return "No result yet"
    line = txt(entry.get("name")) or "Race"
    date_str = fmt_date_short(entry.get("date"))
    if date_str:
        line += f" ({date_str})"
    winner = txt(entry.get("winner"))
    if winner:
        line += f" - Winner: {winner}"
    return line


def format_race_next(entry):
    if not entry:
        return "Not yet scheduled"
    line = txt(entry.get("name")) or "Race"
    venue = txt(entry.get("venue"))
    if venue:
        line += f" - {venue}"
    date_str = fmt_date_short(entry.get("date"))
    if date_str:
        line += f" ({date_str})"
    return line


# ----------------------------------------------------------------- recaps
#
# Recaps are written as short labelled lines rather than one long
# paragraph. On a 7-inch panel a block of labelled lines is far easier
# to read at a glance than a wall of prose.

def header_lines(label, entry):
    lines = []
    ours, theirs = entry.get("team_score"), entry.get("opp_score")
    opp = short_team(entry.get("opponent"))
    where = "vs" if entry.get("is_home") else "at"
    date_str = fmt_date_short(entry.get("date"))
    if ours is not None and theirs is not None:
        verb = {"W": "beat", "L": "lost to", "T": "tied"}[outcome_letter(ours, theirs)]
        lines.append(f"{label} {verb} {opp} {ours}-{theirs}")
    else:
        lines.append(f"{label} {where} {opp}")
    place = "Home" if entry.get("is_home") else "Away"
    meta = ", ".join(p for p in [place, date_str] if p)
    if meta:
        lines.append(meta)
    return lines


def record_lines(entry):
    lines = []
    rec = txt(entry.get("record"))
    standing = txt(entry.get("division_standing"))
    rank = txt(entry.get("ranking"))
    if rec and standing:
        lines.append(f"Record: {rec} ({standing})")
    elif rec and rank:
        lines.append(f"Record: {rec} (AP #{rank})")
    elif rec:
        lines.append(f"Record: {rec}")
    elif standing:
        lines.append(f"Standing: {standing}")
    return lines


def mlb_recap(data, last):
    if not last:
        return no_result_text(data, "game")
    lines = header_lines(txt(data.get("team_label")) or "Yankees", last)
    lines += record_lines(last)

    wp, lp, sv = last.get("winning_pitcher"), last.get("losing_pitcher"), last.get("save_pitcher")
    if wp:
        detail = f"W: {txt(wp.get('name'))}"
        if wp.get("wins") is not None and wp.get("losses") is not None:
            detail += f" ({wp['wins']}-{wp['losses']}"
            if wp.get("era"):
                detail += f", {wp['era']} ERA"
            detail += ")"
        lines.append(detail)
    if lp:
        detail = f"L: {txt(lp.get('name'))}"
        if lp.get("wins") is not None and lp.get("losses") is not None:
            detail += f" ({lp['wins']}-{lp['losses']}"
            if lp.get("era"):
                detail += f", {lp['era']} ERA"
            detail += ")"
        lines.append(detail)
    if sv:
        detail = f"SV: {txt(sv.get('name'))}"
        bits = []
        if sv.get("saves") is not None:
            bits.append(f"{sv['saves']} SV")
        if sv.get("era"):
            bits.append(f"{sv['era']} ERA")
        if bits:
            detail += " (" + ", ".join(bits) + ")"
        lines.append(detail)

    homers = last.get("home_runs") or []
    if homers:
        lines.append("Home runs:")
        for hr in homers:
            season = hr.get("season_total")
            n = hr.get("in_game") or 1
            count = f" x{n}" if n and n > 1 else ""
            tail = f" - {season} on the season" if season else ""
            lines.append(f"  {txt(hr.get('player'))}{count}{tail}")
    return "\n".join(lines)


def nfl_recap(data, last):
    if not last:
        return no_result_text(data, "game")
    lines = header_lines(txt(data.get("team_label")) or "Steelers", last)
    lines += record_lines(last)

    qb = last.get("qb")
    if qb:
        bits = []
        if qb.get("completions") is not None and qb.get("attempts") is not None:
            bits.append(f"{qb['completions']}/{qb['attempts']}")
        if qb.get("pass_yards") is not None:
            bits.append(f"{qb['pass_yards']} yds")
        if qb.get("pass_tds") is not None:
            bits.append(f"{qb['pass_tds']} TD")
        if qb.get("interceptions") is not None:
            bits.append(f"{qb['interceptions']} INT")
        lines.append(f"QB {txt(qb.get('name'))}: " + ", ".join(bits))
    rb = last.get("top_rb")
    if rb:
        bits = []
        if rb.get("carries") is not None:
            bits.append(f"{rb['carries']} car")
        if rb.get("rush_yards") is not None:
            bits.append(f"{rb['rush_yards']} yds")
        if rb.get("rush_tds"):
            bits.append(f"{rb['rush_tds']} TD")
        lines.append(f"RB {txt(rb.get('name'))}: " + ", ".join(bits))
    wr = last.get("top_wr")
    if wr:
        bits = []
        if wr.get("receptions") is not None:
            bits.append(f"{wr['receptions']} rec")
        if wr.get("rec_yards") is not None:
            bits.append(f"{wr['rec_yards']} yds")
        if wr.get("rec_tds"):
            bits.append(f"{wr['rec_tds']} TD")
        lines.append(f"WR {txt(wr.get('name'))}: " + ", ".join(bits))

    to = last.get("turnovers")
    if to:
        lines.append(f"Turnovers: {txt(data.get('team_label')) or 'Team'} {to.get('team', 0)}, "
                     f"{short_team(last.get('opponent'))} {to.get('opponent', 0)}")
    return "\n".join(lines)


def ncaa_recap(data, last):
    if not last:
        return no_result_text(data, "game")
    lines = header_lines(txt(data.get("team_label")) or "UConn", last)
    lines += record_lines(last)

    leaders = last.get("leaders") or {}
    label_map = [("points", "PTS"), ("rebounds", "REB"), ("assists", "AST")]
    got = [(tag, leaders[key]) for key, tag in label_map if leaders.get(key)]
    if got:
        lines.append("Leaders:")
        for tag, entry in got:
            lines.append(f"  {tag}: {txt(entry.get('player'))} {entry.get('value')}")

    pcts = last.get("team_percentages") or {}
    bits = []
    if pcts.get("field_goal"):
        bits.append(f"FG {pcts['field_goal']}%")
    if pcts.get("free_throw"):
        bits.append(f"FT {pcts['free_throw']}%")
    if pcts.get("three_point"):
        bits.append(f"3PT {pcts['three_point']}%")
    if bits:
        lines.append("Team: " + ", ".join(bits))
    return "\n".join(lines)


def nascar_recap(data, last):
    if not last:
        return no_result_text(data, "race")
    lines = []
    name = txt(last.get("name")) or "Most recent race"
    venue = txt(last.get("venue"))
    date_str = fmt_date_short(last.get("date"))
    head = name
    if venue:
        head += f" - {venue}"
    if date_str:
        head += f" ({date_str})"
    lines.append(head)

    winner = txt(last.get("winner"))
    if winner:
        lines.append(f"Winner: {winner}")
    extras = []
    if last.get("lead_changes") is not None:
        extras.append(f"{last['lead_changes']} lead changes")
    if last.get("cautions") is not None:
        extras.append(f"{last['cautions']} cautions")
    if extras:
        lines.append(", ".join(extras).capitalize())

    top10 = last.get("top_10_finishers") or []
    if top10:
        lines.append("")
        lines.append("Top 10 (points earned):")
        for row in top10:
            lines.append(f"  {row.get('position'):>2}. {txt(row.get('driver'))} "
                         f"- {row.get('points_earned')}")
    return "\n".join(lines)


def no_result_text(data, noun):
    nxt = data.get("next") or {}
    line = format_race_next(nxt) if "name" in nxt else format_team_next(nxt)
    if line and line != "Not yet scheduled":
        return f"No completed {noun} result yet.\nNext: {line}"
    return f"No completed {noun} result yet."


# --------------------------------------------------------------- schedule

def team_schedule_line(entry):
    if not entry:
        return ""
    versus = "vs" if entry.get("is_home") else "@"
    line = f"{versus} {short_team(entry.get('opponent'))}"
    date_str = fmt_datetime_short(entry.get("date"))
    return f"{line} - {date_str}" if date_str else line


def race_schedule_line(entry):
    if not entry:
        return ""
    line = txt(entry.get("name")) or "Race"
    venue = txt(entry.get("venue"))
    if venue:
        line += f" - {venue}"
    date_str = fmt_date_short(entry.get("date"))
    return f"{line} ({date_str})" if date_str else line


def build_schedule(key, data):
    events = data.get("schedule")
    if not isinstance(events, list) or not events:
        nxt = data.get("next")
        events = [nxt] if nxt else []
    lines = []
    for event in events:
        line = race_schedule_line(event) if key == "nascar" else team_schedule_line(event)
        if line and line not in lines:
            lines.append(line)
        if len(lines) >= MAX_SCHEDULE_ITEMS:
            break
    return lines or ["No upcoming events are available yet."]


# ------------------------------------------------------- NASCAR standings

def nascar_columns(data):
    """Structured standings table for the multi-column popup.

    Regular season: top 20 by season points.
    Playoffs:       the 16-driver field with total points and playoff wins.
    """
    standings = data.get("standings") or []
    if not standings:
        return None

    playoffs = data.get("standings_mode") == "playoffs"
    items = []

    if playoffs:
        for row in standings[:16]:
            pos = row.get("position")
            name = txt(row.get("last_name")) or txt(row.get("full_name"))
            total = row.get("total_points")
            pwins = row.get("playoff_wins") or 0
            line = f"{pos:>2} {name}"
            if total is not None:
                line += f" {total}"
            line += f" {pwins}W"
            items.append(line)
        title = "Playoffs - points, playoff wins"
        if not data.get("playoffs_underway"):
            title = "Playoff field - seeding, wins"
    else:
        for row in standings[:20]:
            pos = row.get("position")
            name = txt(row.get("last_name")) or txt(row.get("full_name"))
            pts = row.get("points")
            items.append(f"{pos:>2} {name} {pts}" if pts is not None
                         else f"{pos:>2} {name}")
        title = "Top 20 - Season points"

    return {
        "title": title,
        "cols": NASCAR_STANDINGS_COLUMNS,
        "items": items,
    }


# ------------------------------------------------------------- card build

RECAP_BUILDERS = {
    "mlb": mlb_recap,
    "nfl": nfl_recap,
    "ncaam": ncaa_recap,
    "ncaaw": ncaa_recap,
    "nascar": nascar_recap,
}


def has_content(data):
    return bool(data.get("last") or data.get("next") or data.get("schedule"))


def build_card(key, data):
    meta = SPORT_META[key]
    label = txt(data.get("team_label"))
    title = f"{meta['title']} - {label}" if label and label != meta["title"] else meta["title"]

    last_entry = data.get("last") or {}
    next_entry = data.get("next") or {}

    if key == "nascar":
        last_line = format_race_last(last_entry)
        next_line = format_race_next(next_entry)
    else:
        last_line = format_team_last(last_entry)
        next_line = format_team_next(next_entry)

    card = {
        "key": key,
        "title": title,
        "last": last_line,
        "next": next_line,
        "recap": RECAP_BUILDERS[key](data, last_entry),
        "schedule": build_schedule(key, data),
    }
    if key == "nascar":
        cols = nascar_columns(data)
        if cols:
            card["columns"] = cols
    return card


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="scores_input.json")
    parser.add_argument("--out", default="scores.json")
    parser.add_argument("--include-empty-in-season", action="store_true")
    parser.add_argument("--force-all", action="store_true",
                        help="ignore season windows (for testing)")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    now = datetime.now(TZ)
    cards = []
    for key in ("mlb", "nfl", "ncaam", "ncaaw", "nascar"):
        if not args.force_all and not in_season(key, now.month):
            continue
        data = raw.get(key) or {}
        if not args.include_empty_in_season and not has_content(data):
            continue
        cards.append(build_card(key, data))

    out = asciify({"generated_at": now.isoformat(), "cards": cards})
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)

    size = len(json.dumps(out))
    print(f"Wrote {args.out} with {len(cards)} card(s): {[c['key'] for c in cards]}")
    print(f"Feed size: {size} bytes")
    if size > 20000:
        print("WARNING: feed is large; confirm the ESP32 JSON buffer can hold it.")


if __name__ == "__main__":
    main()
