# Lake Michigan Surf MVP — with NWS wind + time toggles
Run:
1) `python -m venv .venv && source .venv/bin/activate`  (Windows: `.venv\Scripts\activate`)
2) `pip install -r requirements.txt`
3) (Optional) set a contact email for NWS: `export NWS_USER_AGENT="LakeSurf/0.1 (you@example.com)"`
4) `python server.py` and open http://localhost:8000

Notes:
- Index page has **Now / +3h / +6h** toggles (query param `h`).
- Forecast uses **NWS hourly** with a fallback mock if network fails.
- Edit spots in `app/data/spots.csv`. Delete `surf.db` to reseed.
