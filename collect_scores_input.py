#!/usr/bin/env python3
"""
collect_scores_input.py
------------------------------------------------------------------
Collects REAL sports data and writes scores_input.json for the
7Display kitchen board.

This is the upstream data collector. It is the piece that was missing
before: generate_scores_json.py only reformats whatever is in
scores_input.json, so if nothing writes real data into that file the
display shows stale or placeholder results.

Sources
  - MLB / NFL / NCAAB / NCAAW : OpticOdds connector, via
      `pplx connector call opticodds opticodds --input '{...}'`
  - NASCAR Cup Series         : NASCAR's own public JSON feed at
      cf.nascar.com (no API key required)

Nothing in this file invents data. Every field is either read from a
source or omitted. If a sport cannot be collected, its section is left
untouched so a partial failure never overwrites good data with junk.

Usage:
  python3 collect_scores_input.py --out scores_input.json
  python3 collect_scores_input.py --out scores_input.json --only mlb,nfl
"""

import argparse
import json
import subprocess
import sys
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
SEASON_YEAR = str(datetime.now(TZ).year)
SCHEDULE_TARGET = 12

UA = {"User-Agent": "Mozilla/5.0 (7Display scores collector)"}

# Stable division membership - used to derive division standing from
# each club's current W-L record.
AL_EAST = [
    "New York Yankees", "Toronto Blue Jays", "Baltimore Orioles",
    "Tampa Bay Rays", "Boston Red Sox",
]
AFC_NORTH = [
    "Pittsburgh Steelers", "Baltimore Ravens",
    "Cincinnati Bengals", "Cleveland Browns",
]

TEAMS = {
    "mlb":   {"sport": "baseball",   "league": "mlb",    "team": "New York Yankees",
              "label": "Yankees",  "division": AL_EAST,   "division_name": "AL East"},
    "nfl":   {"sport": "football",   "league": "nfl",    "team": "Pittsburgh Steelers",
              "label": "Steelers", "division": AFC_NORTH, "division_name": "AFC North"},
    # OpticOdds lists the Huskies as "Connecticut", not "UConn".
    "ncaam": {"sport": "basketball", "league": "ncaab",  "team": "Connecticut",
              "aliases": ["UConn", "UConn Huskies", "Connecticut Huskies"],
              "label": "UConn",    "division": None,      "division_name": None},
    "ncaaw": {"sport": "basketball", "league": "ncaaw",  "team": "Connecticut",
              "aliases": ["UConn", "UConn Huskies", "Connecticut Huskies"],
              "label": "UConn",    "division": None,      "division_name": None},
}


def log(msg):
    print(f"[collect] {msg}", file=sys.stderr)


# ---------------------------------------------------------------- OpticOdds

def oc(path, params=None, timeout=120):
    """Call the OpticOdds connector and return its `data` payload."""
    payload = {"path": path}
    if params:
        payload["params"] = params
    proc = subprocess.run(
        ["pplx", "connector", "call", "opticodds", "opticodds",
         "--input", json.dumps(payload)],
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"opticodds {path} failed: {proc.stderr.strip()[:300]}")
    obj, _ = json.JSONDecoder().raw_decode(proc.stdout)
    return (obj.get("result") or {}).get("data") or {}


# OpticOdds pages /fixtures at 100 rows. Anything that needs a full
# season (schedules, division records) must walk every page or it will
# silently truncate - that is what produced spring-training "last
# games" and 6-game schedules in an earlier build.
MAX_PAGES = 40
PLAYABLE_SEASON_TYPES = {"Regular Season", "Postseason", "Playoffs"}


def oc_fixtures(sport, league, all_pages=True, **kw):
    params = {"sport": sport, "league": league}
    params.update(kw)
    rows, page = [], 1
    while page <= MAX_PAGES:
        params["page"] = page
        payload = oc("/fixtures", params) or {}
        batch = payload.get("data") or []
        rows.extend(batch)
        if not all_pages or not payload.get("has_more") or not batch:
            break
        page += 1
    return rows


def regular_season_only(fixtures):
    """Drop preseason/exhibition games - they are not real results."""
    return [f for f in fixtures
            if (f.get("season_type") or "Regular Season") in PLAYABLE_SEASON_TYPES]


_TEAM_ID_CACHE = {}


def resolve_team_id(cfg):
    """Find the OpticOdds team id for our club (no /teams endpoint exists)."""
    key = (cfg["league"], cfg["team"])
    if key in _TEAM_ID_CACHE:
        return _TEAM_ID_CACHE[key]
    names = team_names(cfg)
    for status in ("unplayed", "completed"):
        for page_limit in (False, True):
            for f in oc_fixtures(cfg["sport"], cfg["league"], all_pages=page_limit,
                                 status=status, season_year=SEASON_YEAR):
                for side in ("home_competitors", "away_competitors"):
                    comp = (f.get(side) or [{}])[0]
                    if comp.get("name") in names and comp.get("id"):
                        _TEAM_ID_CACHE[key] = comp["id"]
                        return comp["id"]
    raise RuntimeError(f"could not resolve team id for {cfg['team']}")


def team_names(cfg):
    return {cfg["team"], *cfg.get("aliases", [])}


def fixture_side(fx, names):
    """Return ('home'|'away', our_competitor, opp_competitor) or None."""
    if isinstance(names, str):
        names = {names}
    home = (fx.get("home_competitors") or [{}])[0]
    away = (fx.get("away_competitors") or [{}])[0]
    if home.get("name") in names:
        return "home", home, away
    if away.get("name") in names:
        return "away", away, home
    return None


def team_fixtures(cfg, status, **kw):
    """Regular/post-season fixtures involving our team, chronological."""
    team_id = resolve_team_id(cfg)
    fx = oc_fixtures(cfg["sport"], cfg["league"], status=status,
                     season_year=SEASON_YEAR, team_id=team_id, **kw)
    names = team_names(cfg)
    out = [f for f in regular_season_only(fx) if fixture_side(f, names)]
    out.sort(key=lambda f: f["start_date"])
    return out


def iso(dt_str):
    return dt_str


def event_entry(fx, cfg):
    side = fixture_side(fx, team_names(cfg))
    if not side:
        return None
    where, _ours, opp = side
    return {
        "is_home": where == "home",
        "opponent": opp.get("name") or "TBD",
        "date": fx["start_date"],
    }


def team_record(fx, cfg):
    """The W-L record OpticOdds attaches to our side of a fixture."""
    side = fixture_side(fx, team_names(cfg))
    if not side:
        return None
    where, _, _ = side
    return fx.get("home_record") if where == "home" else fx.get("away_record")


def parse_record(rec):
    """'82-55' -> (82, 55). Returns None when unparseable."""
    if not rec or "-" not in str(rec):
        return None
    parts = str(rec).split("-")
    try:
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None


def division_standing(cfg):
    """Our club's place in its division, plus games back / games ahead.

    Returns (standing_text, games_text) where games_text is:
      "4 GB"       - trailing the division leader by 4 games
      "2.5 ahead"  - leading, margin over the second-place club
      "tied"       - level with the leader
    Either element may be None when there is not enough data.
    """
    division = cfg.get("division")
    if not division:
        return None, None
    recent = regular_season_only(
        oc_fixtures(cfg["sport"], cfg["league"], status="completed",
                    season_year=SEASON_YEAR))
    latest = {}
    for f in sorted(recent, key=lambda x: x["start_date"]):
        for key, rec_key in (("home_competitors", "home_record"),
                             ("away_competitors", "away_record")):
            comp = (f.get(key) or [{}])[0]
            name = comp.get("name")
            if name in division and f.get(rec_key):
                latest[name] = f[rec_key]

    table = []
    for name in division:
        wl = parse_record(latest.get(name))
        if wl:
            w, l = wl
            pct = w / (w + l) if (w + l) else 0.0
            table.append((name, w, l, pct))
    if len(table) < 2:
        return None, None

    table.sort(key=lambda t: -t[3])
    ours = next((row for row in table if row[0] == cfg["team"]), None)
    if not ours:
        return None, None

    place = table.index(ours) + 1
    standing = f"{ordinal(place)} {cfg['division_name']}"

    # Games back is the classic formula: average of the win gap and the
    # loss gap. When we are on top, the same formula against the
    # second-place club gives the margin we are ahead by.
    _, our_w, our_l, _ = ours
    if place == 1:
        runner_up = table[1]
        margin = ((our_w - runner_up[1]) + (runner_up[2] - our_l)) / 2.0
        if margin <= 0:
            return standing, "tied"
        return standing, f"{trim_half(margin)} ahead"

    leader = table[0]
    behind = ((leader[1] - our_w) + (our_l - leader[2])) / 2.0
    if behind <= 0:
        return standing, "tied"
    return standing, f"{trim_half(behind)} GB"


def trim_half(value):
    """4.0 -> '4', 4.5 -> '4.5' (games back is always a whole or half)."""
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def ordinal(n):
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ------------------------------------------------------- player stat helpers

def player_results(**kw):
    return (oc("/fixtures/player-results", kw) or {}).get("data") or []


def flat_stats(blocks, season_only=True):
    """Yield (fixture, player, team, stats-dict) for each stat line."""
    for b in blocks:
        fx = b.get("fixture") or {}
        if season_only and str(fx.get("season_year")) != SEASON_YEAR:
            continue
        for res in b.get("results") or []:
            for s in res.get("stats") or []:
                yield fx, res.get("player") or {}, res.get("team") or {}, (s.get("stats") or {})


def season_totals(player_id, keys):
    """Sum the given stat keys across this season for one player."""
    totals = defaultdict(int)
    try:
        blocks = player_results(player_id=player_id)
    except Exception as exc:
        log(f"season totals failed for {player_id}: {exc}")
        return totals
    for _fx, _pl, _tm, st in flat_stats(blocks):
        for k in keys:
            totals[k] += st.get(k) or 0
    return totals


def as_number(value):
    """Sacks come in half increments; keep 2.5 but render 3.0 as 3."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value
    return int(num) if num.is_integer() else round(num, 1)


def era_from(earned_runs, outs):
    if not outs:
        return None
    return round(earned_runs * 27.0 / outs, 2)


def pct(made, att):
    if not att:
        return None
    return f"{round(100.0 * made / att, 1)}"


# ----------------------------------------------------------------- MLB

def collect_mlb(cfg):
    completed = team_fixtures(cfg, "completed")
    upcoming = team_fixtures(cfg, "unplayed")
    if not completed and not upcoming:
        raise RuntimeError("no Yankees fixtures returned")

    out = {"team_label": cfg["label"]}

    if upcoming:
        out["next"] = event_entry(upcoming[0], cfg)
        out["schedule"] = [e for e in (event_entry(f, cfg) for f in upcoming[:SCHEDULE_TARGET]) if e]
    if not completed:
        return out

    last_fx = completed[-1]
    side, ours, opp = fixture_side(last_fx, team_names(cfg))
    scores = ((last_fx.get("result") or {}).get("scores") or {})
    our_total = (scores.get(side) or {}).get("total")
    opp_side = "away" if side == "home" else "home"
    opp_total = (scores.get(opp_side) or {}).get("total")

    last = {
        "is_home": side == "home",
        "opponent": opp.get("name"),
        "team_score": our_total,
        "opp_score": opp_total,
        "date": last_fx["start_date"],
        "venue": last_fx.get("venue_name"),
    }

    rec = team_record(last_fx, cfg)
    if rec:
        last["record"] = rec
    standing, games = division_standing(cfg)
    if standing:
        last["division_standing"] = standing
    if games:
        last["games_back"] = games

    # Box score -> pitching decisions and home runs.
    try:
        blocks = player_results(fixture_id=last_fx["id"])
    except Exception as exc:
        log(f"MLB box score unavailable: {exc}")
        blocks = []

    win_p = lose_p = save_p = None
    homers = []
    for _fx, player, team, st in flat_stats(blocks, season_only=False):
        pid, pname = player.get("id"), player.get("name")
        if st.get("wins"):
            win_p = (pid, pname)
        if st.get("losses"):
            lose_p = (pid, pname)
        if st.get("saves"):
            save_p = (pid, pname)
        if st.get("home_runs") and team.get("name") == cfg["team"]:
            homers.append((pid, pname, st.get("home_runs")))

    def pitcher_line(entry, want_saves=False):
        if not entry:
            return None
        pid, pname = entry
        keys = ["wins", "losses", "earned_runs", "outs"] + (["saves"] if want_saves else [])
        tot = season_totals(pid, keys)
        rec = {"name": pname}
        if want_saves:
            rec["saves"] = tot["saves"]
        else:
            rec["wins"] = tot["wins"]
            rec["losses"] = tot["losses"]
        e = era_from(tot["earned_runs"], tot["outs"])
        if e is not None:
            rec["era"] = f"{e:.2f}"
        return rec

    if win_p:
        last["winning_pitcher"] = pitcher_line(win_p)
    if lose_p:
        last["losing_pitcher"] = pitcher_line(lose_p)
    if save_p:
        last["save_pitcher"] = pitcher_line(save_p, want_saves=True)

    hr_list = []
    for pid, pname, n in homers:
        tot = season_totals(pid, ["home_runs"])
        hr_list.append({
            "player": pname,
            "in_game": n,
            "season_total": tot["home_runs"] or n,
        })
    if hr_list:
        last["home_runs"] = hr_list

    out["last"] = last
    return out


# ----------------------------------------------------------------- NFL

def collect_nfl(cfg):
    completed = team_fixtures(cfg, "completed")
    upcoming = team_fixtures(cfg, "unplayed")
    if not completed and not upcoming:
        raise RuntimeError("no Steelers fixtures returned")

    out = {"team_label": cfg["label"]}
    if upcoming:
        out["next"] = event_entry(upcoming[0], cfg)
        out["schedule"] = [e for e in (event_entry(f, cfg) for f in upcoming[:SCHEDULE_TARGET]) if e]
    if not completed:
        return out

    last_fx = completed[-1]
    side, ours, opp = fixture_side(last_fx, team_names(cfg))
    scores = ((last_fx.get("result") or {}).get("scores") or {})
    opp_side = "away" if side == "home" else "home"

    last = {
        "is_home": side == "home",
        "opponent": opp.get("name"),
        "team_score": (scores.get(side) or {}).get("total"),
        "opp_score": (scores.get(opp_side) or {}).get("total"),
        "date": last_fx["start_date"],
    }
    rec = team_record(last_fx, cfg)
    if rec:
        last["record"] = rec
    standing, games = division_standing(cfg)
    if standing:
        last["division_standing"] = standing
    if games:
        last["games_back"] = games

    try:
        blocks = player_results(fixture_id=last_fx["id"])
    except Exception as exc:
        log(f"NFL box score unavailable: {exc}")
        blocks = []

    # OpticOdds reuses one `interceptions` key for both sides of the ball:
    # on a QB it means picks thrown, on a defender it means picks caught.
    # Position is what disambiguates them.
    names = team_names(cfg)
    ours_rows = []
    give_us = give_them = 0.0
    sacks_for = sacks_allowed = 0.0

    for _fx, player, team, st in flat_stats(blocks, season_only=False):
        is_ours = team.get("name") in names
        position = (player.get("position") or "").upper()

        picks_thrown = (st.get("interceptions") or 0) if position == "QB" else 0
        giveaways = picks_thrown + (st.get("fumbles_lost") or 0)

        if is_ours:
            give_us += giveaways
            ours_rows.append((player, st))
            sacks_for += st.get("sacks") or 0
            sacks_allowed += st.get("passing_sacks") or 0
        else:
            give_them += giveaways

    # Takeaways are the other team's giveaways, so the two always
    # reconcile instead of being counted from two different stat keys.
    if give_us or give_them:
        last["turnovers"] = {"team": as_number(give_us),
                             "opponent": as_number(give_them),
                             "forced": as_number(give_them)}
    if sacks_for or sacks_allowed:
        last["sacks"] = {"by_team": as_number(sacks_for),
                         "allowed": as_number(sacks_allowed)}

    def best(rows, key):
        pick = None
        for player, st in rows:
            v = st.get(key) or 0
            if v and (pick is None or v > pick[2]):
                pick = (player, st, v)
        return pick

    qb = best(ours_rows, "passing_yards")
    if qb:
        p, st, _ = qb
        last["qb"] = {
            "name": p.get("name"),
            "completions": st.get("passing_completions") or st.get("completions"),
            "attempts": st.get("passing_attempts") or st.get("attempts"),
            "pass_yards": st.get("passing_yards"),
            "pass_tds": st.get("passing_touchdowns"),
            "interceptions": st.get("interceptions"),  # thrown, this is a QB
            "rating": st.get("qb_rating"),
            "sacked": st.get("passing_sacks"),
            "rush_yards": st.get("rushing_yards"),
        }
    rb = best(ours_rows, "rushing_yards")
    if rb:
        p, st, _ = rb
        last["top_rb"] = {
            "name": p.get("name"),
            "carries": st.get("rushing_attempts"),
            "rush_yards": st.get("rushing_yards"),
            "rush_tds": st.get("rushing_touchdowns"),
            "long": st.get("longest_rush"),
        }
    wr = best(ours_rows, "receiving_yards")
    if wr:
        p, st, _ = wr
        last["top_wr"] = {
            "name": p.get("name"),
            "receptions": st.get("receptions"),
            "rec_yards": st.get("receiving_yards"),
            "rec_tds": st.get("receiving_touchdowns"),
            "long": st.get("longest_reception"),
        }

    out["last"] = last
    return out


# ------------------------------------------------------------ NCAA (M/W)

def ap_ranking(cfg):
    """UConn's AP poll ranking.

    OpticOdds does not carry polls, so this reads the current AP Top 25
    from the open web. It returns None on any failure - a missing rank
    simply drops that line from the recap rather than guessing a number.
    """
    which = "men's" if cfg["league"] == "ncaab" else "women's"
    try:
        import pplx_sdk  # available in the sandbox that runs this job
        pages = pplx_sdk.content.fetch(
            ["https://apnews.com/hub/ap-top-25-college-basketball-poll"],
            prompt=(f"What is Connecticut (UConn) {which} basketball's current "
                    "AP Top 25 rank? Reply with just the number, or NONE if "
                    "UConn is unranked or the poll is not shown."),
        )
        text = (pages[0].content or "").strip()
        digits = "".join(ch for ch in text if ch.isdigit())[:2]
        if digits and 1 <= int(digits) <= 25:
            return str(int(digits))
    except Exception as exc:
        log(f"AP ranking unavailable for {cfg['league']}: {exc}")
    return None


def collect_ncaa(cfg):
    completed = team_fixtures(cfg, "completed")
    upcoming = team_fixtures(cfg, "unplayed")
    if not completed and not upcoming:
        raise RuntimeError(f"no {cfg['league']} fixtures returned")

    out = {"team_label": cfg["label"]}
    if upcoming:
        out["next"] = event_entry(upcoming[0], cfg)
        out["schedule"] = [e for e in (event_entry(f, cfg) for f in upcoming[:SCHEDULE_TARGET]) if e]
    if not completed:
        return out

    last_fx = completed[-1]
    side, ours, opp = fixture_side(last_fx, team_names(cfg))
    scores = ((last_fx.get("result") or {}).get("scores") or {})
    opp_side = "away" if side == "home" else "home"

    last = {
        "is_home": side == "home",
        "opponent": opp.get("name"),
        "team_score": (scores.get(side) or {}).get("total"),
        "opp_score": (scores.get(opp_side) or {}).get("total"),
        "date": last_fx["start_date"],
    }
    rec = team_record(last_fx, cfg)
    if rec:
        last["record"] = rec

    rank = ap_ranking(cfg)
    if rank:
        last["ranking"] = rank

    try:
        blocks = player_results(fixture_id=last_fx["id"])
    except Exception as exc:
        log(f"{cfg['league']} box score unavailable: {exc}")
        blocks = []

    names = team_names(cfg)
    rows = [(p, st) for _f, p, t, st in flat_stats(blocks, season_only=False)
            if t.get("name") in names]

    def leader(key):
        pick = None
        for p, st in rows:
            v = st.get(key) or 0
            if v and (pick is None or v > pick[1]):
                pick = (p.get("name"), v)
        return {"player": pick[0], "value": pick[1]} if pick else None

    leaders = {}
    for label, key in (("points", "points"), ("rebounds", "rebounds"), ("assists", "assists")):
        got = leader(key)
        if got:
            leaders[label] = got
    if leaders:
        last["leaders"] = leaders

    def team_sum(*keys):
        return sum((st.get(k) or 0) for _p, st in rows for k in keys)

    percentages = {}
    fg = pct(team_sum("field_goals_made"), team_sum("field_goals_attempted"))
    ft = pct(team_sum("free_throws_made"), team_sum("free_throws_attempted"))
    tp = pct(team_sum("three_point_field_goals_made"), team_sum("three_point_field_goals_attempted"))
    if fg:
        percentages["field_goal"] = fg
    if ft:
        percentages["free_throw"] = ft
    if tp:
        percentages["three_point"] = tp
    if percentages:
        last["team_percentages"] = percentages

    out["last"] = last
    return out


# --------------------------------------------------------------- NASCAR

NASCAR_SERIES = 1  # Cup Series
PLAYOFF_FIELD_SIZE = 16
PLAYOFF_BASE_POINTS = 2000  # every playoff driver resets to this


# "Shane Van Gisbergen" -> "Van Gisbergen", not "Gisbergen".
# "Ricky Stenhouse Jr"  -> "Stenhouse", not "Jr".
NAME_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}
NAME_PARTICLES = {"van", "von", "de", "del", "della", "der", "di",
                  "da", "la", "le", "du", "dos", "st.", "mc"}


def surname(full_name):
    cleaned = str(full_name or "").strip()
    parts = [p for p in cleaned.split() if p]
    while len(parts) > 1 and parts[-1].lower().strip(",") in NAME_SUFFIXES:
        parts.pop()
    if not parts:
        return cleaned
    start = len(parts) - 1
    while start > 1 and parts[start - 1].lower() in NAME_PARTICLES:
        start -= 1
    return " ".join(parts[start:])


def nascar_get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read())


def collect_nascar():
    year = SEASON_YEAR
    races = nascar_get(f"https://cf.nascar.com/cacher/{year}/{NASCAR_SERIES}/race_list_basic.json")
    points_races = [r for r in races if r.get("race_type_id") == 1]
    now = datetime.now(TZ).replace(tzinfo=None)

    def race_dt(r):
        return datetime.fromisoformat(r["race_date"])

    completed = [r for r in points_races if race_dt(r) < now]
    upcoming = [r for r in points_races if race_dt(r) >= now]

    out = {}
    if upcoming:
        nxt = upcoming[0]
        out["next"] = {"name": nxt["race_name"], "date": nxt["race_date"][:10],
                       "venue": nxt["track_name"]}
        out["schedule"] = [
            {"name": r["race_name"], "date": r["race_date"][:10], "venue": r["track_name"]}
            for r in upcoming[:SCHEDULE_TARGET]
        ]
    if not completed:
        return out

    last = completed[-1]
    results = nascar_get(
        f"https://cf.nascar.com/cacher/{year}/{NASCAR_SERIES}/{last['race_id']}/raceResults.json")

    finishers = sorted(
        [r for r in results if (r.get("finishing_position") or 0) >= 1],
        key=lambda r: r["finishing_position"])

    last_block = {
        "name": last["race_name"],
        "date": last["race_date"][:10],
        "venue": last["track_name"],
    }
    if finishers:
        last_block["winner"] = finishers[0]["driver_fullname"]
        last_block["top_10_finishers"] = [
            {"position": r["finishing_position"],
             "driver": r["driver_fullname"],
             "points_earned": r.get("points_earned") or 0}
            for r in finishers[:10]
        ]
    if last.get("number_of_cautions") is not None:
        last_block["cautions"] = last["number_of_cautions"]
    if last.get("number_of_lead_changes") is not None:
        last_block["lead_changes"] = last["number_of_lead_changes"]
    out["last"] = last_block

    # ---- standings -------------------------------------------------
    #
    # Two modes. During the regular season this is the top 20 in season
    # points. Once the playoff field is set it becomes the 16-driver
    # playoff grid with playoff points and playoff wins.
    #
    # NASCAR's feed exposes a playoff_points_earned field but leaves it
    # at zero, so playoff points are computed from the documented rules:
    #   5 per race win + 1 per stage win + regular-season finish bonus.
    def load_race(r):
        rid = r["race_id"]
        base = f"https://cf.nascar.com/cacher/{year}/{NASCAR_SERIES}/{rid}"
        try:
            finish = nascar_get(f"{base}/raceResults.json")
        except Exception as exc:
            log(f"NASCAR race {rid} results failed: {exc}")
            finish = []
        try:
            stages = (nascar_get(f"{base}/weekend-feed.json")["weekend_race"][0]
                      .get("stage_results") or [])
        except Exception:
            stages = []
        return r, finish, stages

    with ThreadPoolExecutor(8) as pool:
        every = list(pool.map(load_race, completed))

    playoff_races = [r for r in points_races if r.get("playoff_round")]
    playoff_start = min((race_dt(r) for r in playoff_races), default=None)

    names = {}
    season_points = defaultdict(int)
    race_wins = defaultdict(int)
    stage_wins = defaultdict(int)
    playoff_wins = defaultdict(int)
    playoff_race_points = defaultdict(int)

    for r, finish, stages in every:
        is_playoff_race = bool(playoff_start and race_dt(r) >= playoff_start)
        for row in finish:
            did = row.get("driver_id")
            if did is None:
                continue
            names[did] = row["driver_fullname"]
            earned = row.get("points_earned") or 0
            season_points[did] += earned
            if is_playoff_race:
                playoff_race_points[did] += earned
            if row.get("finishing_position") == 1:
                race_wins[did] += 1
                if is_playoff_race:
                    playoff_wins[did] += 1
        for stage in stages:
            for row in (stage.get("results") or []):
                if row.get("finishing_position") == 1 and row.get("driver_id"):
                    stage_wins[row["driver_id"]] += 1

    # A driver who has not declared for Cup points scores none, and does
    # not claim a playoff berth even if they win a race.
    eligible = [d for d in names if season_points[d] > 0]
    if not eligible:
        return out

    regular_order = sorted(eligible, key=lambda d: -season_points[d])
    REG_SEASON_BONUS = {1: 15, 2: 10, 3: 8, 4: 7, 5: 6,
                        6: 5, 7: 4, 8: 3, 9: 2, 10: 1}
    reg_bonus = {d: REG_SEASON_BONUS.get(i, 0)
                 for i, d in enumerate(regular_order, 1)}

    if playoff_start is not None:
        winners = sorted([d for d in eligible if race_wins[d] > 0],
                         key=lambda d: (-race_wins[d], -season_points[d]))
        winless = [d for d in regular_order if race_wins[d] == 0]
        field = (winners + winless)[:PLAYOFF_FIELD_SIZE]

        seeded = []
        for d in field:
            playoff_points = (5 * race_wins[d]) + stage_wins[d] + reg_bonus.get(d, 0)
            seeded.append((d, playoff_points))
        seeded.sort(key=lambda t: (-(t[1] + playoff_race_points[t[0]]),
                                   -t[1], -season_points[t[0]]))

        out["standings"] = [
            {"position": i,
             "last_name": surname(names[d]),
             "full_name": names[d],
             "playoff_points": pp,
             "total_points": PLAYOFF_BASE_POINTS + pp + playoff_race_points[d],
             "playoff_wins": playoff_wins[d],
             "season_wins": race_wins[d],
             "stage_wins": stage_wins[d]}
            for i, (d, pp) in enumerate(seeded, 1)
        ]
        out["standings_mode"] = "playoffs"
        out["standings_basis"] = "Playoff standings - points, playoff wins"
        out["playoffs_underway"] = any(
            race_dt(r) >= playoff_start for r, _f, _s in every)
        return out

    official_pos = {r["driver_id"]: r["points_position"]
                    for r in results if r.get("points_position")}
    ranked = sorted([d for d in eligible if d in official_pos],
                    key=lambda d: official_pos[d])[:20]
    if ranked:
        leader = season_points[ranked[0]]
        out["standings"] = [
            {"position": official_pos[d],
             "last_name": surname(names[d]),
             "full_name": names[d],
             "points": season_points[d],
             "behind": season_points[d] - leader}
            for d in ranked
        ]
        out["standings_mode"] = "regular"
        out["standings_basis"] = "Season points (NASCAR official standings order)"
    return out


# ----------------------------------------------------------------- main

COLLECTORS = {
    "mlb":    lambda: collect_mlb(TEAMS["mlb"]),
    "nfl":    lambda: collect_nfl(TEAMS["nfl"]),
    "ncaam":  lambda: collect_ncaa(TEAMS["ncaam"]),
    "ncaaw":  lambda: collect_ncaa(TEAMS["ncaaw"]),
    "nascar": collect_nascar,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="scores_input.json")
    ap.add_argument("--only", default="", help="comma list, e.g. mlb,nfl")
    args = ap.parse_args()

    wanted = [k.strip() for k in args.only.split(",") if k.strip()] or list(COLLECTORS)

    try:
        with open(args.out, "r", encoding="utf-8") as fh:
            existing = json.load(fh)
    except Exception:
        existing = {}

    result = dict(existing)
    ok, failed = [], []
    for key in wanted:
        try:
            log(f"collecting {key} ...")
            section = COLLECTORS[key]()
            if section:
                result[key] = section
                ok.append(key)
            else:
                failed.append(f"{key} (empty)")
        except Exception as exc:
            log(f"{key} FAILED: {exc}")
            failed.append(f"{key} ({exc})")

    result["collected_at"] = datetime.now(TZ).isoformat()
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)

    log(f"wrote {args.out}: ok={ok} failed={failed}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
