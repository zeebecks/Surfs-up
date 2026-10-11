"""Presentation of cached Open-Meteo weather and daylight forecasts."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from .weather import FORECAST_MAX_AGE, number, parse_time, stamp, utcnow

LOCAL_ZONE = ZoneInfo("America/Chicago")


def weather_description(code, is_day):
    if code == 0:
        return ("Sunny", "sun") if is_day else ("Clear night", "moon")
    if code in (1, 2):
        return "Partly cloudy", "partly-cloudy" if is_day else "cloud"
    if code == 3:
        return "Overcast", "cloud"
    if code in (45, 48):
        return "Fog", "fog"
    if code in (51, 53, 55, 56, 57):
        return "Drizzle", "rain"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "Rain", "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "Snow", "snow"
    if code in (95, 96, 99):
        return "Thunderstorms", "storm"
    return "Weather unavailable", "unknown"


def parse_conditions(payload):
    hourly = payload.get("hourly", {})
    rows = []
    for index, value in enumerate(hourly.get("time", [])):
        start = parse_time(value)

        def field(name):
            values = hourly.get(name, [])
            return values[index] if index < len(values) else None

        code = number(field("weather_code"), 0, 99)
        is_day = field("is_day")
        description, icon = weather_description(code, is_day == 1)
        rows.append(
            {
                "time": stamp(start),
                "end": stamp(start + timedelta(hours=1)),
                "temperature_f": number(field("temperature_2m"), -150, 150),
                "description": description,
                "icon": icon,
            }
        )
    if not any(row["temperature_f"] is not None for row in rows):
        raise ValueError("No usable air temperature forecast")
    daily = payload.get("daily", {})
    days = {}
    for index, date in enumerate(daily.get("time", [])):
        day = {}
        for name in ("sunrise", "sunset"):
            values = daily.get(name, [])
            value = values[index] if index < len(values) else None
            day[name] = stamp(parse_time(value)) if value else None
        days[date] = day
    return {"rows": rows, "days": days, "source": "Open-Meteo", "daylight_history": True}


async def fetch_conditions(client, spot):
    response = await client.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": spot.lat,
            "longitude": spot.lng,
            "hourly": "temperature_2m,weather_code,is_day",
            "daily": "sunrise,sunset",
            "temperature_unit": "fahrenheit",
            "timezone": "UTC",
            # After midnight UTC it is still the previous day in Wisconsin.
            # Keep that day's daylight events available for evening forecasts.
            "past_days": 1,
            "forecast_days": 4,
        },
    )
    response.raise_for_status()
    return parse_conditions(response.json())


def conditions_at(store, spot_id, at):
    result = {
        "temperature_f": None,
        "description": "Weather unavailable",
        "icon": "unknown",
        "sunrise": None,
        "sunset": None,
        "status": "unavailable",
        "fetched_at": None,
    }
    data = store.get(f"conditions:{spot_id}")
    if not data:
        return result
    row = next(
        (
            row
            for row in data.get("rows", [])
            if parse_time(row["time"]) <= at < parse_time(row["end"])
        ),
        None,
    )
    if row:
        result.update({key: value for key, value in row.items() if key not in ("time", "end")})
        recent = (
            data.get("fetched_at") and utcnow() - parse_time(data["fetched_at"]) < FORECAST_MAX_AGE
        )
        result.update(
            status="demo"
            if store.demo
            else "fresh"
            if recent and not data.get("error")
            else "stale",
            fetched_at=data.get("fetched_at"),
        )
    # UTC sunset can fall on the next calendar date. Match events by the
    # event's local date rather than the provider's UTC daily grouping.
    local_date = at.astimezone(LOCAL_ZONE).date()
    for day in data.get("days", {}).values():
        for name in ("sunrise", "sunset"):
            value = day.get(name)
            if value and parse_time(value).astimezone(LOCAL_ZONE).date() == local_date:
                result[name] = value
    return result
