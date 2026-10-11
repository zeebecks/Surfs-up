"""Weather selection, daylight dates, and explicit missing-data behavior."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
from test_app import Base

from app.services.conditions import conditions_at, parse_conditions, weather_description
from app.services.weather import WeatherStore, stamp


class ConditionsTests(Base):
    def test_fetch_requests_fahrenheit_and_daylight(self):
        def respond(request):
            self.assertEqual(request.url.params["temperature_unit"], "fahrenheit")
            self.assertEqual(request.url.params["timezone"], "UTC")
            self.assertEqual(request.url.params["past_days"], "1")
            self.assertEqual(request.url.params["daily"], "sunrise,sunset")
            return httpx.Response(
                200,
                json={
                    "hourly": {
                        "time": ["2026-10-10T23:00"],
                        "temperature_2m": [65],
                        "weather_code": [3],
                        "is_day": [1],
                    }
                },
            )

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                return await WeatherStore().fetch_conditions(client, self.spot)

        data = asyncio.run(run())
        self.assertEqual(data["rows"][0]["temperature_f"], 65)
        self.assertEqual(data["rows"][0]["description"], "Overcast")

    def test_temperature_and_daylight_follow_selected_local_day(self):
        at = datetime(2026, 10, 10, 23, tzinfo=timezone.utc)
        payload = {
            "hourly": {
                "time": [stamp(at), stamp(at + timedelta(hours=3))],
                "temperature_2m": [-4, 59],
                "weather_code": [3, 0],
                "is_day": [1, 0],
            },
            "daily": {
                "time": ["2026-10-10", "2026-10-11"],
                "sunrise": ["2026-10-10T11:57", "2026-10-11T11:58"],
                "sunset": ["2026-10-11T00:16", "2026-10-12T00:14"],
            },
        }
        store = WeatherStore()
        store.records["conditions:spot"] = {
            **parse_conditions(payload),
            "fetched_at": stamp(at),
        }
        with patch("app.services.conditions.utcnow", return_value=at):
            selected = conditions_at(store, "spot", at)
            self.assertEqual(selected["temperature_f"], -4)
            self.assertEqual(selected["description"], "Overcast")
            self.assertEqual(selected["sunset"], "2026-10-11T00:16:00+00:00")
            night = conditions_at(store, "spot", at + timedelta(hours=3))
            self.assertEqual(night["temperature_f"], 59)
            self.assertEqual(night["icon"], "moon")
            self.assertEqual(night["sunset"], selected["sunset"])
            missing = conditions_at(store, "spot", at + timedelta(hours=24))
            self.assertIsNone(missing["temperature_f"])
            self.assertEqual(missing["sunset"], "2026-10-12T00:14:00+00:00")

    def test_missing_and_stale_weather_are_explicit(self):
        at = datetime.now(timezone.utc)
        store = WeatherStore()
        self.assertIsNone(conditions_at(store, "spot", at)["sunrise"])
        store.records["conditions:spot"] = {
            "rows": [
                {"time": stamp(at), "end": stamp(at + timedelta(hours=1)), "temperature_f": 60}
            ],
            "fetched_at": stamp(at - timedelta(hours=5)),
        }
        self.assertEqual(conditions_at(store, "spot", at)["status"], "stale")
        store.records["conditions:spot"]["fetched_at"] = stamp(at)
        store.records["conditions:spot"]["error"] = "offline"
        self.assertEqual(conditions_at(store, "spot", at)["status"], "stale")
        self.assertEqual(weather_description(None, True)[1], "unknown")
        for code, icon in [(45, "fog"), (61, "rain"), (71, "snow"), (95, "storm")]:
            self.assertEqual(weather_description(code, True)[1], icon)

    def test_demo_renders_weather_and_time_without_external_requests(self):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.services.weather import weather

        weather.load_demo(self.spots)
        with patch("httpx.AsyncClient.get", side_effect=AssertionError("External request")):
            response = TestClient(app).get("/spots/north-pier-two-rivers?h=24")
        self.assertEqual(response.status_code, 200)
        for text in [
            "Air temperature",
            "Partly cloudy",
            "Sunrise",
            "Sunset",
            "Local forecast time",
            "Sample weather",
        ]:
            self.assertIn(text, response.text)
