"""Opt-in smoke test: public providers and local pages; uses a temporary database."""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(buoys_only=False):
    with tempfile.TemporaryDirectory(prefix="lake-surf-live-") as temp:
        os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(temp) / "audit.db")

        from app.database import init_db
        from app.services.spot_repo import get_all_spots, seed_spots_if_empty
        from app.services.weather import WeatherStore, utcnow

        init_db()
        seed_spots_if_empty()
        store = WeatherStore()
        spots = [] if buoys_only else get_all_spots()
        asyncio.run(store.refresh(spots))
        print("Provider coverage (each source may be independently unavailable):")
        for spot in spots:
            fc = store.forecast(spot.id, utcnow())
            wind = store.get(f"wind:{spot.id}") or {}
            waves = store.get(f"waves:{spot.id}") or {}
            print(
                spot.id,
                "wind:",
                fc.get("source"),
                fc["wind_kts"],
                fc["status"],
                "wind hours:",
                len(wind.get("rows", [])),
                "waves:",
                fc["wave_height_m"],
                fc["wave_status"],
                "cell:",
                waves.get("grid"),
            )
        print("Buoy readings:")
        for station in store.stations():
            print(
                station["id"],
                station["status"],
                "wind:",
                station["measurements"].get("wind_kts"),
                "waves (m):",
                station["measurements"].get("wave_height_m"),
                "error:",
                station["error"],
            )

    return check_local()


def check_local():
    import httpx

    failures = 0
    print("Local application responses:")
    for path in (
        "/",
        "/?h=6",
        "/buoys",
        "/spots/sheboygan-elbow",
        "/crew",
        "/about",
        "/api/status",
    ):
        started = time.perf_counter()
        try:
            response = httpx.get("http://localhost:8000" + path, timeout=10)
            failures += response.status_code != 200
            print(
                path,
                response.status_code,
                round((time.perf_counter() - started) * 1000),
                "ms",
                len(response.content),
                "bytes",
            )
        except httpx.HTTPError as error:
            failures += 1
            print(path, type(error).__name__)
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(
        check_local() if "--local-only" in sys.argv else main(buoys_only="--buoys-only" in sys.argv)
    )
