import json, subprocess
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

zone = ZoneInfo('America/New_York')
today = datetime.now(zone).date()
start = datetime.combine(today, time.min, tzinfo=zone)
end = datetime.combine(today + timedelta(days=7), time.min, tzinfo=zone)
payload = json.dumps({'start_date': start.isoformat(), 'end_date': end.isoformat(), 'queries': None})
out_path = '/home/user/workspace/primary_events_cron.json'
try:
    proc = subprocess.run(
        ['pplx', 'connector', 'call', 'gcal', 'search_calendar', '--input', payload, '--stdout-preview=10000'],
        text=True, capture_output=True, timeout=120
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f'connector exit {proc.returncode}')
    data = json.loads(proc.stdout)
    events = data.get('result', {}).get('calendar_event_list', {}).get('events', [])
    arr = [{'title': e.get('title', ''), 'start': e.get('start', ''), 'is_all_day': bool(e.get('is_all_day', False))} for e in events]
except Exception as exc:
    arr = []
    print(f'calendar connector failed; using []: {exc}')
with open(out_path, 'w') as f:
    json.dump(arr, f, indent=2)
    f.write('\n')
print(json.dumps({'today': str(today), 'start': start.isoformat(), 'end': end.isoformat(), 'events': len(arr)}))
