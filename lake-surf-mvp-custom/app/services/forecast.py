from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import os            # ← add this
import re
import httpx
import logging

logger = logging.getLogger("forecast")

UA = os.getenv("NWS_USER_AGENT", "LakeSurf/0.1 (local-dev)")
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/geo+json",
}


@dataclass
class Forecast:
    wind_kts: float
    wind_dir_deg: int
    gust_kts: float
    wave_height_m: float | None = None
    source: str = "mock"

CARD2DEG = {"N":0,"NNE":22,"NE":45,"ENE":67,"E":90,"ESE":112,"SE":135,"SSE":157,
            "S":180,"SSW":202,"SW":225,"WSW":247,"W":270,"WNW":292,"NW":315,"NNW":337}

def _mph_to_kts(mph: float) -> float: return mph * 0.868976
def _parse_speed(txt: str | None) -> float:
    if not txt: return 0.0
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", txt)]
    if not nums: return 0.0
    return _mph_to_kts(sum(nums)/len(nums))

def _dir_to_deg(val) -> int:
    if val is None: return 0
    try: return int(val)
    except Exception: return CARD2DEG.get(str(val).strip().upper(), 0)

def _mock(lat: float, lng: float) -> Forecast:
    seed = int(abs(lat*1000) + abs(lng*1000)) % 360
    wind_dir = (seed * 7) % 360
    wind_kts = 12 + (seed % 20)
    gust_kts = wind_kts + 4 + (seed % 6)
    return Forecast(wind_kts=wind_kts, wind_dir_deg=wind_dir, gust_kts=gust_kts, wave_height_m=None, source="mock")

def get_forecast_for(lat: float, lng: float, at: datetime | None = None) -> Forecast:
    at = at or datetime.now(timezone.utc)
    try:
        with httpx.Client(timeout=12, headers=HEADERS) as client:
            # 1) points lookup
            points = client.get(f"https://api.weather.gov/points/{lat},{lng}")
            points.raise_for_status()
            pjson = points.json()
            props = pjson.get("properties")
            if not isinstance(props, dict):
                raise RuntimeError(f"NWS points payload missing properties (keys={list(pjson.keys())[:6]})")

            # 2) pick hourly if present, else regular forecast
            hourly_url = props.get("forecastHourly") or props.get("forecast")
            if not hourly_url:
                raise RuntimeError("No forecastHourly or forecast URL in properties")

            # 3) fetch forecast
            fc = client.get(hourly_url)
            fc.raise_for_status()
            fjson = fc.json()
            periods = (fjson.get("properties") or {}).get("periods")
            if not isinstance(periods, list) or not periods:
                raise RuntimeError("Forecast payload missing periods")

            # 4) choose period containing or closest to 'at'
            best = None; best_diff = None
            for per in periods:
                st = datetime.fromisoformat(per["startTime"].replace("Z","+00:00"))
                et = datetime.fromisoformat(per["endTime"].replace("Z","+00:00"))
                if st <= at <= et:
                    best = per; break
                diff = abs((st - at).total_seconds())
                if best is None or diff < best_diff:
                    best = per; best_diff = diff

            wind_kts = _parse_speed(best.get("windSpeed"))
            gust_kts = _parse_speed(best.get("windGust")) or (wind_kts + 4)
            wind_dir = _dir_to_deg(best.get("windDirection"))
            return Forecast(wind_kts=wind_kts, wind_dir_deg=wind_dir, gust_kts=gust_kts, wave_height_m=None, source="nws")

    except Exception as e:
        logger.exception("NWS fallback due to error")
        return _mock(lat, lng)
