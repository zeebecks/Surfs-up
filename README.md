# SurfsUP

A wind-first surf dashboard for the Wisconsin shore of Lake Michigan. Compare six local spots, follow the northern and southern offshore buoys, and check cameras and hourly forecasts without opening a dozen tabs.

Built with Python, FastAPI, Jinja, SQLite, and a small amount of vanilla JavaScript. The app is designed to remain useful when an upstream source is missing or offline.

## Run locally

Python 3.12 or newer is recommended; checks run on 3.13.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

Open **http://localhost:8000**. On Windows, activate with `.venv\Scripts\activate`.

Already have the virtual environment? Activate it, install the updated requirements, and restart the server. Uvicorn reloads application changes while developing. The server's first weather refresh runs in the background; the page offers **Update this view** when new conditions are ready. Opening pages never waits for the providers.

Optional configuration (export in your shell; `.env` is not automatically loaded):

```sh
export NWS_USER_AGENT="LakeSurf/0.2 (you@example.com)"
export NOTES_ADMIN_PASSWORD="choose-a-private-shared-password"
```

See [.env.example](.env.example) for all settings. Without `NOTES_ADMIN_PASSWORD`, field reports are read-only. Never commit real passwords.

## What you can do

- Compare Kewaunee, Two Rivers North Pier, Manitowoc South Pier, Sheboygan Elbow, Sheboygan Blue Harbor, and Port Washington.
- Check wind speed/direction, gusts where available, and modeled wave height/period/direction.
- Select Now, +3h, +6h, +12h, or +24h; open a spot for a 48-hour hourly table.
- Save favorites on your device; sort north-to-south, by wind setup, or by surf estimate.
- Explore spot markers, switch to an independent Windy map, or expand the map to the offshore buoys.
- Follow northern/southern basin and Rawley Point wave measurements, plus wind observations from the northern buoy, Sheboygan, and Port Washington, with per-measurement timestamps and recent wind trends.
- Load cameras on demand and follow original camera links when embeds are unavailable.
- Save dated field reports without overwriting the persistent local guide.
- Make public, same-day crew check-ins. Removal uses a token saved on the device that created the check-in.

## Data and trust

| Source | Role |
| --- | --- |
| [NWS API](https://www.weather.gov/documentation/services-web-api) | Primary hourly wind, plus gusts from the raw forecast grid |
| [Open-Meteo Weather](https://open-meteo.com/en/docs) | Labeled fallback wind forecast when NWS cannot supply usable data |
| [Open-Meteo Marine](https://open-meteo.com/en/docs/marine-weather-api) | Offshore modeled wave height, period, direction; water-cell selection with a distance check |
| [NOAA NDBC](https://www.ndbc.noaa.gov/) | Stations 45002, 45214, 45210, SGNW3, and PWAW3 |
| [Windy](https://www.windy.com/) | Independent embedded wind map with its own timeline |
| [Windfinder](https://www.windfinder.com/) | Additional forecast links on supported spot pages |
| [GLOS Seagull](https://seagull.glos.org/) | Link to discover additional local observing platforms; not yet ingested |

All six model locations were checked during implementation. Nearby spots can share a wave-model cell. Model output is **not** a measurement of waves breaking at the beach.

The southern buoy is [South Michigan Spotter (45214)](https://www.ndbc.noaa.gov/station_page.php?station=45214), replacing 45007. [Rawley Point East (45210)](https://www.ndbc.noaa.gov/station_page.php?station=45210) adds wave observations east of the Two Rivers area. Both can report waves without wind; their cards and map popups show the available measurements.

A station does not need every sensor to be useful. Wave height appears on every offshore card, including the homepage. Station status reflects available readings; each field retains its own freshness label. Each sensor retains its own observation time; a missing field is never interpreted as zero. Observations older than two hours are labeled stale. The parser looks back at most 24 hours for each sensor; cached readings can remain visible beyond that during an outage, with their original age.

Forecast retrieval timestamps describe when this app fetched data, not the model run time. Forecasts older than three hours, or whose latest refresh failed, are marked stale and excluded from ratings. Forecasts are selected only inside a valid interval. Today's buoy readings never become tomorrow's forecast.

## Ratings: experimental v2

**Wind setup** estimates building potential from each spot's existing fetch preferences, wind strength, and gustiness. It remains available with wind data alone. Favorable direction cannot produce a high score in calm wind.

**Surf estimate** additionally requires fresh modeled wave height, period, and direction. It combines wave energy, shoreline exposure, wave period, and surface wind. Flat modeled water scores zero; offshore cleanup can rate better than strong onshore wind when a wave field already exists.

Confidence and source availability remain separate from the score. Existing fixed spot bonuses/penalties are no longer used. The UI explains each estimate and the score bands.

This is a documented heuristic, not a calibrated surf forecast. It does not yet calculate fetch distance, wind duration, wave travel time, or pier shelter. Buoys provide regional context rather than automatically adjusting a beach's score. Calibrating with dated local sessions is the next step. See [/about](http://localhost:8000/about) or [scoring.py](app/services/scoring.py).

## Architecture

```text
Background refresh (bounded concurrent requests)
    ├── NWS wind/grid → Open-Meteo wind fallback
    ├── Open-Meteo Marine
    └── NDBC station text feeds
             ↓ normalized values, valid times, source metadata
      SQLite weather_cache + memory cache
             ↓ no provider requests during page rendering
      FastAPI routes → Jinja pages → optional map/camera enhancements
```

Successful sources are cached for ten minutes. Failed sources are retried after a minute. NWS point-to-grid lookups are cached for seven days. A shared HTTP client and a four-request-workflow concurrency limit keep source access bounded. Last successful payloads survive process restarts and failed refreshes.

SQLite tables are created on startup. Spot seeding inserts missing IDs without replacing existing notes or metadata. Existing `surf.db` files remain compatible; the only new table is `weather_cache`. Stable guide text is loaded from `app/data/spots.csv`, while field reports live in the database. Editing CSV metadata for an existing spot does not silently update its database row; perform a deliberate migration for those changes.

The background worker is intended for the project's single-process deployment. Multiple application workers would each refresh independently; coordinate refresh ownership before scaling out.

## Offline demo

```sh
SURF_DEMO=1 python server.py
```

This explicitly enables labeled fixture data in memory. It never writes demo weather to the persistent live cache. Stop the server and restart without `SURF_DEMO=1` to return to live mode. Cameras and third-party maps still require their external providers; forecast/observation fixtures work offline.

## Checks

```sh
pip install -r requirements-dev.txt
ruff check app tests scripts server.py
ruff format --check app tests scripts server.py
python -m unittest discover -s tests -v
node --check app/static/app.js
node --check app/static/map.js
```

Tests use temporary databases and injected provider responses. They cover data parsing, stale/missing conditions, scoring behavior, persistence, note escaping, check-in validation/deletion, route rendering, and cache reuse. They do not contact external providers or modify the local `surf.db`. GitHub Actions runs the checks on pushes and pull requests.

An optional live smoke test uses a temporary database and reads the local server:

```sh
python scripts/check_live_sources.py
```

It reports provider availability independently; an offline buoy is not a broken app. This is not part of CI because live data and provider availability change.

## UI verification status

The original app was reviewed from the supplied Chrome screenshot. The revised templates render successfully for live, missing-data, and demo states, and JavaScript passes syntax checks. Automated visual/browser interaction QA could not run because no browser was connected to the agent runtime. Responsive layouts, map interactions, camera playback, and device storage should still receive a real-browser pass at 375, 768, and 1440px widths. No screenshot or browser-pass claim is implied by the backend tests.

## Next calibration work

Add known good/poor session examples, refine spot exposure and shelter settings, evaluate additional GLOS sensors around the existing corridor, and compare model waves against local observations over time. The current app is deliberately scoped to the original six Wisconsin spots.
