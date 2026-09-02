# 7Display Scores Feed

Data feed for the 7Display kitchen board's Scores screen.

The ESP32 fetches one file over plain HTTPS (no auth, no redirects):

```
https://raw.githubusercontent.com/sds0520/7display-scores/main/scores.json
```

## Pipeline

```
collect_scores_input.py  ->  scores_input.json  ->  generate_scores_json.py  ->  scores.json
      (real data in)            (source data)            (formatting)            (what the board reads)
```

| File | Role |
| --- | --- |
| `collect_scores_input.py` | Collects **real** results, stats, standings and schedules. This is the upstream collector. |
| `scores_input.json` | Source data. Written by the collector; not hand-edited. |
| `generate_scores_json.py` | Season filtering and text formatting. Does **not** fetch anything. |
| `scores.json` | Flattened feed the display downloads. |

**Important:** `generate_scores_json.py` only reformats whatever is already in
`scores_input.json`. It cannot make data current. If `scores_input.json` holds
placeholder or stale values, the board will faithfully display them. Only
`collect_scores_input.py` brings in live data.

## Data sources

| Sport | Source | Notes |
| --- | --- | --- |
| MLB (Yankees) | OpticOdds | Box score, pitching decisions, HR hitters, record. Season W-L/ERA and HR totals aggregated across the season. |
| NFL (Steelers) | OpticOdds | QB/RB/WR leaders, turnovers, record. |
| NCAAM / NCAAW (UConn) | OpticOdds | Leaders and team shooting percentages. Listed as "Connecticut" upstream. |
| AP ranking | apnews.com | Best-effort; omitted rather than guessed when unavailable. |
| NASCAR Cup | `cf.nascar.com` public JSON | Race results, points earned, stage winners, standings. No API key needed. |

Division standing (AL East / AFC North) is derived from each club's current
W-L record, since neither source publishes a standings table directly.

## Running it

```bash
python3 collect_scores_input.py --out scores_input.json
python3 generate_scores_json.py --input scores_input.json --out scores.json
```

Collect a single sport while testing:

```bash
python3 collect_scores_input.py --out scores_input.json --only nascar
```

Ignore season windows when testing out-of-season sports:

```bash
python3 generate_scores_json.py --force-all
```

A partial failure never destroys good data: if one sport cannot be collected,
that section of `scores_input.json` is left exactly as it was and the run
reports which sports succeeded and which did not.

## Schedule

The feed is rebuilt and published at **2:00 AM Eastern** daily. The board
picks it up at **3:00 AM**, and also refreshes shortly after any Wi-Fi
reconnect.

## Season windows

| Sport | Months shown |
| --- | --- |
| MLB | March - November |
| NFL | August - February |
| NCAAM / NCAAW | December - April |
| NASCAR | February - November |

Cards for out-of-season sports are omitted so the screen stays uncluttered.
UConn plays in November, but the college cards intentionally do not appear
until December; see `SEASON_WINDOWS` in `generate_scores_json.py`.

## NASCAR standings modes

The standings table switches automatically:

- **Regular season** - top 20 by season points, ordered by NASCAR's own
  `points_position` field.
- **Playoffs** - the 16-driver field with total points and playoff wins.

NASCAR's feed carries a `playoff_points_earned` field but leaves it at zero,
so playoff points are computed from the published rules: **5 per race win,
1 per stage win, plus the regular-season finish bonus** (15-10-8-7-6-5-4-3-2-1
for the top ten). Each playoff driver resets to a 2,000-point base.

The field is built the way NASCAR builds it: race winners first (ranked by
wins, then points), with the remaining berths going to the highest winless
drivers on points. A driver who has not declared for Cup points scores none
and does not take a playoff berth even if they win a race - that is why Corey
Heim's two 2026 wins do not put him in the field.

## Feed shape

```json
{
  "generated_at": "...",
  "cards": [
    {
      "key": "nascar",
      "title": "NASCAR",
      "last": "short line for the card",
      "next": "short line for the card",
      "recap": "detailed text shown when Last is tapped",
      "schedule": ["up to 12 upcoming events, shown when Next is tapped"],
      "columns": {
        "title": "Season points",
        "cols": 2,
        "items": ["1 Hamlin 1026", "..."]
      }
    }
  ]
}
```

`columns` is optional and currently only used by NASCAR, which renders the
standings as a multi-column grid under the recap text.

All strings in `scores.json` are ASCII-folded, because the LVGL Montserrat
fonts compiled into the sketch cover ASCII only - an accented name would
otherwise render as blank boxes on the panel. `scores_input.json` keeps the
correct spelling.

Keep `scores.json` under roughly 24 KB - that is the JSON buffer size in
`7Display_Full.ino`. The generator prints the feed size and warns past 20 KB.
