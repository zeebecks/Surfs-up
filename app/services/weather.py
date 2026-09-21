"""Small, persistent provider cache. Network I/O never runs in a page request."""

import asyncio
import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from threading import RLock

import httpx
from sqlalchemy import text

from .util import get_session

log = logging.getLogger(__name__)
UTC = timezone.utc
REFRESH_SECONDS = 600
FORECAST_MAX_AGE = timedelta(hours=3)
OBS_MAX_AGE = timedelta(hours=2)

STATIONS = [
    dict(
        id="45002",
        name="North Michigan",
        kind="Offshore buoy",
        lat=45.344,
        lng=-86.411,
        context="Northern basin · watch northerly wind building down the lake",
        scope="basin",
    ),
    dict(
        id="45214",
        name="South Michigan Spotter",
        kind="Offshore buoy",
        lat=42.674,
        lng=-87.026,
        context="Southern basin · measured waves and water temperature",
        scope="basin",
    ),
    dict(
        id="45210",
        name="Rawley Point East",
        kind="Offshore buoy",
        lat=44.055,
        lng=-87.050,
        context="Off Rawley Point · measured waves east of the Two Rivers area",
        scope="basin",
    ),
    dict(
        id="SGNW3",
        name="Sheboygan",
        kind="Coastal wind station",
        lat=43.749,
        lng=-87.693,
        context="Local wind context for Sheboygan; not a breaking-wave measurement",
        scope="local",
    ),
    dict(
        id="PWAW3",
        name="Port Washington",
        kind="Coastal wind station",
        lat=43.388,
        lng=-87.867,
        context="Local wind context for Port Washington; wind readings are useful on their own",
        scope="local",
    ),
]
for station in STATIONS:
    station["url"] = f"https://www.ndbc.noaa.gov/station_page.php?station={station['id']}"


def utcnow():
    return datetime.now(UTC)


def stamp(value):
    return value.isoformat()


def parse_time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def number(value, minimum=None, maximum=None):
    try:
        result = float(value)
        if (
            not math.isfinite(result)
            or (minimum is not None and result < minimum)
            or (maximum is not None and result > maximum)
        ):
            return None
        return result
    except (ValueError, TypeError):
        return None


def direction(value):
    names = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()
    if isinstance(value, str) and value.upper() in names:
        return names.index(value.upper()) * 22.5
    result = number(value, 0, 360)
    return result % 360 if result is not None else None


def speed(value):
    """NWS textual mph or knots; unknown units and missing data stay missing."""
    import re

    if not isinstance(value, str):
        return None
    values = [float(v) for v in re.findall(r"\d+(?:\.\d+)?", value)]
    if not values:
        return None
    factor = 0.868976 if "mph" in value else 1 if "kt" in value or "knot" in value else None
    return sum(values) / len(values) * factor if factor is not None else None


def parse_nws(payload):
    rows = []
    for p in payload.get("properties", {}).get("periods", []):
        try:
            start, end = parse_time(p["startTime"]), parse_time(p["endTime"])
        except (KeyError, ValueError, TypeError):
            continue
        if end <= start or end - start > timedelta(hours=2):
            continue
        rows.append(
            dict(
                time=stamp(start),
                end=stamp(end),
                wind_kts=speed(p.get("windSpeed")),
                wind_dir_deg=direction(p.get("windDirection")),
                gust_kts=speed(p.get("windGust")),
            )
        )
    if not any(r["wind_kts"] is not None for r in rows):
        raise ValueError("No usable hourly wind forecast")
    return rows


def add_nws_gusts(rows, payload):
    """The hourly summary omits gusts; obtain them from the NWS raw grid."""
    import re

    field = payload.get("properties", {}).get("windGust", {})
    factor = {
        "wmoUnit:km_h-1": 1 / 1.852,
        "wmoUnit:m_s-1": 1.943844,
        "wmoUnit:kn": 1,
        "wmoUnit:mi_h-1": 0.868976,
    }.get(field.get("uom"))
    if factor is None:
        return rows
    for entry in field.get("values", []):
        try:
            start_text, duration = entry["validTime"].split("/")
            match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", duration)
            if not match:
                continue
            days, hours, minutes = (int(value or 0) for value in match.groups())
            start = parse_time(start_text)
            end = start + timedelta(days=days, hours=hours, minutes=minutes)
            value = number(entry.get("value"), 0)
            if value is None:
                continue
            for row in rows:
                if start <= parse_time(row["time"]) < end:
                    row["gust_kts"] = round(value * factor, 3)
        except (KeyError, ValueError, TypeError):
            continue
    return rows


def parse_openmeteo(payload, marine=False):
    hourly = payload.get("hourly", {})
    rows = []
    fields = (
        {
            "wave_height": "wave_height_m",
            "wave_period": "wave_period_s",
            "wave_direction": "wave_dir_deg",
        }
        if marine
        else {
            "wind_speed_10m": "wind_kts",
            "wind_gusts_10m": "gust_kts",
            "wind_direction_10m": "wind_dir_deg",
        }
    )
    for i, value in enumerate(hourly.get("time", [])):
        start = parse_time(value)
        row = dict(time=stamp(start), end=stamp(start + timedelta(hours=1)))
        for key, target in fields.items():
            values = hourly.get(key, [])
            row[target] = (
                number(values[i], 0, 360 if "direction" in key else None)
                if i < len(values)
                else None
            )
        rows.append(row)
    primary = "wave_height_m" if marine else "wind_kts"
    if not any(r[primary] is not None for r in rows):
        raise ValueError("No usable model values")
    return rows


def parse_ndbc(raw, now=None):
    """Read independent sensor timestamps; never interpret MM or sentinels as zero."""
    now = now or utcnow()
    lines = raw.splitlines()
    header = next((line.lstrip("#").split() for line in lines if line.startswith("#YY")), None)
    if not header:
        raise ValueError("Missing NDBC header")
    fields = {
        "WDIR": ("wind_dir_deg", 1, 0, 360),
        "WSPD": ("wind_kts", 1.943844, 0, 100),
        "GST": ("gust_kts", 1.943844, 0, 120),
        "WVHT": ("wave_height_m", 1, 0, 30),
        "DPD": ("wave_period_s", 1, 0.1, 40),
        "MWD": ("wave_dir_deg", 1, 0, 360),
        "WTMP": ("water_temp_c", 1, -5, 45),
    }
    rows = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != len(header):
            continue
        try:
            year, month, day, hour, minute = map(int, parts[:5])
            observed = datetime(year, month, day, hour, minute, tzinfo=UTC)
        except (ValueError, TypeError):
            continue
        if observed > now + timedelta(minutes=5) or now - observed > timedelta(hours=24):
            continue
        values = dict(zip(header, parts))
        row = {"time": stamp(observed)}
        for key, (target, factor, low, high) in fields.items():
            v = number(values.get(key), low, high)
            # Legacy numeric missing markers used by NDBC archives.
            if values.get(key) in {"99.0", "99.00", "999", "999.0", "9999"}:
                v = None
            row[target] = round(v * factor, 3) if v is not None else None
        rows.append(row)
    rows.sort(key=lambda row: row["time"], reverse=True)
    latest = {}
    for target, *_ in fields.values():
        match = next((row for row in rows if row[target] is not None), None)
        latest[target] = {"value": match[target], "time": match["time"]} if match else None
    return {"measurements": latest, "history": rows[:150]}


class WeatherStore:
    def __init__(self):
        self.records = {}
        self.lock = RLock()
        self.refreshing = False
        self.ready = False
        self.demo = False
        self._guard = None

    def load(self):
        with get_session() as db:
            records = db.execute(text("SELECT key, payload FROM weather_cache")).all()
        with self.lock:
            for key, payload in records:
                try:
                    self.records[key] = json.loads(payload)
                except (ValueError, TypeError):
                    log.warning("Ignoring malformed cache record %s", key)
            self.ready = bool(self.records)

    def get(self, key):
        with self.lock:
            return json.loads(json.dumps(self.records.get(key)))

    def save(self, key, payload):
        with get_session() as db:
            db.execute(
                text(
                    "INSERT INTO weather_cache (key,payload) VALUES (:key,:payload) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload"
                ),
                {"key": key, "payload": json.dumps(payload)},
            )
            db.commit()
        with self.lock:
            self.records[key] = payload

    async def refresh(self, spots):
        if self._guard is None:
            self._guard = asyncio.Lock()
        if self._guard.locked():
            return
        async with self._guard:
            self.refreshing = True
            semaphore = asyncio.Semaphore(4)
            headers = {
                "User-Agent": os.getenv("NWS_USER_AGENT", "LakeSurf/0.2 (local development)")
            }
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10, connect=5), headers=headers, follow_redirects=True
            ) as client:

                async def cached(key, fetch):
                    async with semaphore:
                        previous = self.get(key)
                        now = utcnow()
                        retry_after = 60 if previous and previous.get("error") else REFRESH_SECONDS
                        if previous and now - parse_time(previous["attempted_at"]) < timedelta(
                            seconds=retry_after
                        ):
                            return
                        try:
                            payload = await asyncio.wait_for(fetch(client), timeout=24)
                            payload.update(
                                fetched_at=stamp(now), attempted_at=stamp(now), error=None
                            )
                        except (
                            httpx.HTTPError,
                            ValueError,
                            KeyError,
                            TypeError,
                            TimeoutError,
                        ) as error:
                            log.warning(
                                "Weather source %s unavailable: %s", key, type(error).__name__
                            )
                            payload = previous or {"rows": [], "fetched_at": None}
                            payload.update(
                                attempted_at=stamp(now), error="Source temporarily unavailable"
                            )
                        self.save(key, payload)

                jobs = []
                for spot in spots:
                    jobs.extend(
                        [
                            cached(f"wind:{spot.id}", lambda c, s=spot: self.fetch_wind(c, s)),
                            cached(f"waves:{spot.id}", lambda c, s=spot: self.fetch_waves(c, s)),
                        ]
                    )
                for station in STATIONS:
                    jobs.append(
                        cached(f"buoy:{station['id']}", lambda c, s=station: self.fetch_buoy(c, s))
                    )
                try:
                    await asyncio.gather(*jobs)
                finally:
                    self.refreshing = False
                    self.ready = True

    async def fetch_wind(self, client, spot):
        try:
            point_key = f"point:{spot.id}"
            point = self.get(point_key)
            if not point or utcnow() - parse_time(point["fetched_at"]) > timedelta(days=7):
                response = await client.get(
                    f"https://api.weather.gov/points/{spot.lat:.4f},{spot.lng:.4f}"
                )
                response.raise_for_status()
                url = response.json()["properties"]["forecastHourly"]
                if not url.startswith("https://api.weather.gov/"):
                    raise ValueError("Unexpected forecast host")
                point = {"url": url, "fetched_at": stamp(utcnow())}
                self.save(point_key, point)
            response = await client.get(point["url"])
            response.raise_for_status()
            rows = parse_nws(response.json())
            if point["url"].endswith("/forecast/hourly"):
                try:
                    grid = await client.get(
                        point["url"].removesuffix("/forecast/hourly"), timeout=4
                    )
                    grid.raise_for_status()
                    add_nws_gusts(rows, grid.json())
                except (httpx.HTTPError, ValueError, TypeError):
                    pass  # Gusts are optional; do not discard a valid wind forecast.
            return {"rows": rows, "source": "NWS", "source_url": point["url"]}
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            response = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": spot.lat,
                    "longitude": spot.lng,
                    "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
                    "wind_speed_unit": "kn",
                    "timezone": "UTC",
                    "forecast_days": 3,
                },
            )
            response.raise_for_status()
            return {
                "rows": parse_openmeteo(response.json()),
                "source": "Open-Meteo",
                "source_url": "https://open-meteo.com/en/docs",
            }

    async def fetch_waves(self, client, spot):
        response = await client.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
                "latitude": spot.lat,
                "longitude": spot.lng,
                "hourly": "wave_height,wave_period,wave_direction",
                "timezone": "UTC",
                "forecast_days": 3,
                "cell_selection": "sea",
            },
        )
        response.raise_for_status()
        data = response.json()
        lat, lng = number(data.get("latitude")), number(data.get("longitude"))
        if lat is None or lng is None or abs(lat - spot.lat) > 0.3 or abs(lng - spot.lng) > 0.3:
            raise ValueError("Model cell is too far from this spot")
        return {
            "rows": parse_openmeteo(data, marine=True),
            "source": "Open-Meteo Marine",
            "source_url": "https://open-meteo.com/en/docs/marine-weather-api",
            "grid": [lat, lng],
        }

    async def fetch_buoy(self, client, station):
        response = await client.get(f"https://www.ndbc.noaa.gov/data/realtime2/{station['id']}.txt")
        response.raise_for_status()
        return {**parse_ndbc(response.text), "source": "NOAA NDBC", "source_url": station["url"]}

    def forecast(self, spot_id, at):
        result = {
            "wind_kts": None,
            "gust_kts": None,
            "wind_dir_deg": None,
            "wave_height_m": None,
            "wave_period_s": None,
            "wave_dir_deg": None,
            "status": "unavailable",
            "wave_status": "unavailable",
        }
        now = utcnow()
        for kind in ("wind", "waves"):
            data = self.get(f"{kind}:{spot_id}")
            if not data:
                continue
            row = next(
                (
                    row
                    for row in data.get("rows", [])
                    if parse_time(row["time"]) <= at < parse_time(row["end"])
                ),
                None,
            )
            if not row:
                continue
            result.update({k: v for k, v in row.items() if k not in {"time", "end"}})
            recent = (
                data.get("fetched_at") and now - parse_time(data["fetched_at"]) < FORECAST_MAX_AGE
            )
            state = (
                "demo" if self.demo else "fresh" if recent and not data.get("error") else "stale"
            )
            if kind == "wind":
                result.update(
                    status=state,
                    source=data.get("source"),
                    fetched_at=data.get("fetched_at"),
                    source_url=data.get("source_url"),
                )
            else:
                result.update(
                    wave_status=state,
                    wave_source=data.get("source"),
                    wave_fetched_at=data.get("fetched_at"),
                    grid=data.get("grid"),
                )
        return result

    def stations(self):
        now = utcnow()
        result = []
        for station in STATIONS:
            data = self.get(f"buoy:{station['id']}") or {}
            measurements = data.get("measurements", {})
            for field, reading in measurements.items():
                if reading:
                    reading["status"] = (
                        "demo"
                        if self.demo
                        else "fresh"
                        if now - parse_time(reading["time"]) < OBS_MAX_AGE
                        else "stale"
                    )
            # A wave-only buoy is still reporting. Each sensor keeps its own age.
            statuses = {reading["status"] for reading in measurements.values() if reading}
            status = next(
                (state for state in ("demo", "fresh", "stale") if state in statuses),
                "unavailable",
            )
            result.append(
                {
                    **station,
                    "measurements": measurements,
                    "history": data.get("history", []),
                    "status": status,
                    "error": data.get("error"),
                    "fetched_at": data.get("fetched_at"),
                }
            )
        return result

    def load_demo(self, spots):
        """Explicit in-memory fixtures; never persist demo readings into the live cache."""
        now = utcnow().replace(minute=0, second=0, microsecond=0)
        self.demo = True
        for i, spot in enumerate(spots):
            rows, waves = [], []
            for hour in range(49):
                time = now + timedelta(hours=hour)
                rows.append(
                    dict(
                        time=stamp(time),
                        end=stamp(time + timedelta(hours=1)),
                        wind_kts=round(max(2, 16 + i - hour * 0.25), 1),
                        gust_kts=round(max(4, 21 + i - hour * 0.25), 1),
                        wind_dir_deg=45 + (hour // 8) * 22.5,
                    )
                )
                waves.append(
                    dict(
                        time=stamp(time),
                        end=stamp(time + timedelta(hours=1)),
                        wave_height_m=round(max(0.1, 1.1 - hour * 0.018 + i * 0.03), 2),
                        wave_period_s=4.8,
                        wave_dir_deg=67.5,
                    )
                )
            for kind, data in (("wind", rows), ("waves", waves)):
                self.records[f"{kind}:{spot.id}"] = dict(
                    rows=data, source="Demo fixture", fetched_at=stamp(now), attempted_at=stamp(now)
                )
        for i, station in enumerate(STATIONS):
            history = [
                dict(
                    time=stamp(now - timedelta(minutes=30 * j)),
                    wind_kts=round(18 + i + math.sin(j / 3) * 3, 1),
                    wind_dir_deg=45,
                    gust_kts=24 + i,
                )
                for j in range(24)
            ]
            measurements = {
                key: {"value": value, "time": stamp(now)}
                for key, value in history[0].items()
                if key != "time"
            }
            if station["scope"] == "basin":
                measurements.update(
                    wave_height_m={"value": 1.1, "time": stamp(now)},
                    wave_period_s={"value": 5, "time": stamp(now)},
                    water_temp_c={"value": 17, "time": stamp(now)},
                )
                for row in history:
                    row.update(wave_height_m=1.1, wave_period_s=5, water_temp_c=17)
            if station["id"] in {"45214", "45210"}:
                for field in ("wind_kts", "wind_dir_deg", "gust_kts"):
                    measurements[field] = None
                    for row in history:
                        row[field] = None
            self.records[f"buoy:{station['id']}"] = dict(
                measurements=measurements, history=history, fetched_at=stamp(now)
            )
        self.ready = True


weather = WeatherStore()


async def refresh_loop(spots):
    while True:
        try:
            await weather.refresh(spots)
        except Exception:
            log.exception("Weather refresh failed; serving the previous cache")
        # Successful sources retain their ten-minute TTL; retry failures sooner.
        await asyncio.sleep(60)
