#!/usr/bin/env python3
"""
generate_calendar_json.py
------------------------------------------------------------------
Builds calendar.json for the 7Display kitchen board.

The display cannot do Google's OAuth, so this script assembles a plain
JSON file that the board fetches over a single unauthenticated HTTPS
GET. Two kinds of source are merged:

  --primary-json   events already pulled from the gcal connector
  --ics            any number of shared iCal URLs, as "URL=Label"

Output shape (unchanged from the original feed):

  {
    "generated_at": "...-04:00",
    "today_date": "YYYY-MM-DD",
    "tomorrow_date": "YYYY-MM-DD",
    "today":    [ {title, time, all_day, who} ],
    "tomorrow": [ ... ],
    "week":     [ {date, day_name, events: [...]} ]   # 7 days from today
  }

Usage:
  python3 generate_calendar_json.py \
      --primary-json primary_events.json --primary-label "Steven" \
      --ics "https://...basic.ics=Abby" \
      --out 7display-calendar/calendar.json
"""

import argparse
import json
import sys
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
WEEK_DAYS = 7
UA = {"User-Agent": "Mozilla/5.0 (7Display calendar feed)"}


def log(msg):
    print(f"[calendar] {msg}", file=sys.stderr)


def to_local(value):
    """Normalise a datetime/date/ISO string into (date, time_or_None)."""
    if value is None:
        return None, None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        return value, None
    else:
        text = str(value).strip()
        if not text:
            return None, None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.strptime(text[:10], "%Y-%m-%d").date(), None
            except ValueError:
                return None, None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    local = dt.astimezone(TZ)
    return local.date(), local


def make_event(title, day, when, all_day, who):
    return {
        "_date": day,
        "title": str(title).strip() or "(no title)",
        "time": "All day" if all_day else when.strftime("%-I:%M %p"),
        "all_day": bool(all_day),
        "who": who,
    }


def load_primary(path, label):
    """Events already fetched from the connector and written to disk."""
    events = []
    if not path:
        return events
    try:
        with open(path, "r", encoding="utf-8") as fh:
            rows = json.load(fh)
    except Exception as exc:
        log(f"primary events unreadable ({exc}) - continuing without them")
        return events
    for row in rows or []:
        all_day = bool(row.get("is_all_day"))
        day, when = to_local(row.get("start"))
        if not day:
            continue
        if not all_day and when is None:
            all_day = True
        events.append(make_event(row.get("title"), day, when, all_day, label))
    log(f"{label}: {len(events)} event(s) from primary calendar")
    return events


def load_ics(url, label, window_start, window_end):
    """Expand one shared iCal feed across the window, recurrences included."""
    try:
        import icalendar
        import recurring_ical_events
    except ImportError:
        log("icalendar/recurring-ical-events not installed - skipping ICS")
        return []
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
        cal = icalendar.Calendar.from_ical(raw)
        occurrences = recurring_ical_events.of(cal).between(window_start, window_end)
    except Exception as exc:
        log(f"{label}: ICS fetch/parse failed ({exc}) - skipping this calendar")
        return []

    events = []
    for item in occurrences:
        start = item.get("DTSTART")
        if start is None:
            continue
        value = start.dt
        all_day = not isinstance(value, datetime)
        day, when = to_local(value)
        if not day:
            continue
        events.append(make_event(item.get("SUMMARY", ""), day, when, all_day, label))
    log(f"{label}: {len(events)} event(s) from ICS")
    return events


def sort_key(event):
    """All-day items first, then chronological."""
    if event["all_day"]:
        return (0, "")
    try:
        parsed = datetime.strptime(event["time"], "%I:%M %p")
        return (1, parsed.strftime("%H:%M"))
    except ValueError:
        return (1, event["time"])


def day_bucket(events, day):
    rows = sorted((e for e in events if e["_date"] == day), key=sort_key)
    return [{k: v for k, v in e.items() if k != "_date"} for e in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary-json")
    ap.add_argument("--primary-label", default="Steven")
    ap.add_argument("--ics", action="append", default=[],
                    help='Repeatable. Format: "https://...basic.ics=Label"')
    ap.add_argument("--out", default="calendar.json")
    args = ap.parse_args()

    now = datetime.now(TZ)
    today = now.date()
    window_start = datetime.combine(today, datetime.min.time(), tzinfo=TZ)
    window_end = window_start + timedelta(days=WEEK_DAYS)

    events = load_primary(args.primary_json, args.primary_label)
    for spec in args.ics:
        url, _, label = spec.rpartition("=")
        if not url:
            log(f"malformed --ics value, expected URL=Label: {spec[:60]}")
            continue
        events.extend(load_ics(url, label or "Shared", window_start, window_end))

    tomorrow = today + timedelta(days=1)
    week = []
    for offset in range(WEEK_DAYS):
        day = today + timedelta(days=offset)
        week.append({
            "date": day.isoformat(),
            "day_name": day.strftime("%A, %b %-d"),
            "events": day_bucket(events, day),
        })

    out = {
        "generated_at": now.isoformat(),
        "today_date": today.isoformat(),
        "tomorrow_date": tomorrow.isoformat(),
        "today": day_bucket(events, today),
        "tomorrow": day_bucket(events, tomorrow),
        "week": week,
    }

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)

    total = sum(len(d["events"]) for d in week)
    log(f"wrote {args.out}: today={len(out['today'])} "
        f"tomorrow={len(out['tomorrow'])} week={total}")


if __name__ == "__main__":
    main()
