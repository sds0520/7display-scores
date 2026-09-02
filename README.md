# 7Display Scores Feed

Small JSON data feed for the 7Display kitchen board's Scores screen.

- `scores.json` - current data. Refreshed automatically on a recurring schedule.
- `generate_scores_json.py` - the script that builds scores.json from normalized sports data.

Fetched directly by the ESP32 display via a plain HTTPS GET (no auth) at:
https://raw.githubusercontent.com/sds0520/7display-scores/main/scores.json
