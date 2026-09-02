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
| NASCAR Cup | `cf.nascar.com` public JSON | Race results, points earned, official standings order. No API key needed. |

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
| NCAAM / NCAAW | November - April |
| NASCAR | February - November |

Cards for out-of-season sports are omitted so the screen stays uncluttered.
College basketball starts in November rather than December so UConn's opening
month is not hidden; see `SEASON_WINDOWS` in `generate_scores_json.py`.

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
top-20 points standings as a multi-column grid under the recap text.

Keep `scores.json` under roughly 24 KB - that is the JSON buffer size in
`7Display_Full.ino`. The generator prints the feed size and warns past 20 KB.
