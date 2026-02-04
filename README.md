# Lake Michigan Surf MVP
Simple surf-forecast and crew check-in MVP for Lake Michigan spots.

## Features
- NWS hourly wind forecast with a local fallback when the network is unavailable.
- Time toggles for now, +3h, and +6h (query param `h`).
- Spot notes with name and timestamp (latest edit wins).
- Crew check-ins with client-side delete token stored in local storage.
- SQLite persistence with seed data from `app/data/spots.csv`.

## Getting started
1) `python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`)
2) `pip install -r requirements.txt`
3) Optional: set a contact email for NWS
   - `export NWS_USER_AGENT="LakeSurf/0.1 (you@example.com)"`
4) `python server.py` and open http://localhost:8000

## Notes
- Forecast data uses the NWS hourly endpoint and gracefully falls back if the request fails.
- Check-in deletion is only available on the same device because the token is stored in local storage.
- The SQLite database is created on first run and seeded from `app/data/spots.csv`.
