"""Offline regression checks. Never opens or modifies the developer's surf.db."""

import asyncio
import atexit
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

_test_directory = tempfile.TemporaryDirectory(prefix="lake-surf-tests-")
atexit.register(_test_directory.cleanup)
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(_test_directory.name) / "test.db")
os.environ["WEATHER_REFRESH"] = "0"
os.environ["SURF_DEMO"] = "0"

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import engine, init_db
from app.main import app
from app.services.scoring import rate
from app.services.spot_repo import get_all_spots, seed_spots_if_empty
from app.services.weather import (
    WeatherStore,
    add_nws_gusts,
    direction,
    parse_ndbc,
    parse_nws,
    speed,
    stamp,
    utcnow,
    weather,
)


def fixture_rows(now=None):
    now = (now or utcnow()).replace(minute=0, second=0, microsecond=0)
    return [
        dict(
            time=stamp(now + timedelta(hours=i)),
            end=stamp(now + timedelta(hours=i + 1)),
            wind_kts=15 + i,
            wind_dir_deg=90,
            gust_kts=20 + i,
        )
        for i in range(49)
    ]


def forecast(**changes):
    return {
        "wind_kts": 15,
        "wind_dir_deg": 90,
        "gust_kts": 20,
        "wave_height_m": 1,
        "wave_period_s": 5,
        "wave_dir_deg": 90,
        "status": "fresh",
        "wave_status": "fresh",
        **changes,
    }


class Base(unittest.TestCase):
    def setUp(self):
        init_db()
        with engine.begin() as db:
            for table in ("spots", "checkins", "weather_cache"):
                db.execute(text(f"DELETE FROM {table}"))
        seed_spots_if_empty()
        weather.records.clear()
        weather.ready = False
        weather.demo = False
        weather.refreshing = False
        self.spots = get_all_spots()
        self.spot = next(s for s in self.spots if s.id == "sheboygan-elbow")


class ScoringTests(Base):
    def test_flat_water_cannot_score_as_surf(self):
        result = rate(self.spot, forecast(wave_height_m=0))
        self.assertEqual(result["surf_score"], 0)
        self.assertGreater(result["wind_score"], 0)

    def test_calm_wind_has_no_building_potential(self):
        result = rate(self.spot, forecast(wind_kts=0, gust_kts=0, wave_height_m=0))
        self.assertEqual(result["wind_score"], 0)
        self.assertEqual(result["surf_score"], 0)

    def test_wind_only_is_still_useful(self):
        result = rate(self.spot, forecast(wave_height_m=None))
        self.assertIsNotNone(result["wind_score"])
        self.assertIsNone(result["surf_score"])
        self.assertEqual(result["confidence"], "Wind model only")

    def test_missing_wind_is_not_north_or_calm(self):
        for field in ("wind_kts", "wind_dir_deg"):
            self.assertIsNone(rate(self.spot, forecast(**{field: None}))["wind_score"])

    def test_offshore_cleanup_beats_strong_onshore_for_existing_waves(self):
        clean = rate(self.spot, forecast(wind_kts=8, wind_dir_deg=270, gust_kts=10))
        choppy = rate(self.spot, forecast(wind_kts=28, wind_dir_deg=90, gust_kts=34))
        self.assertGreater(clean["surf_score"], choppy["surf_score"])
        self.assertLess(clean["wind_score"], choppy["wind_score"])

    def test_wrong_wave_direction_does_not_rate_well(self):
        self.assertEqual(rate(self.spot, forecast(wave_dir_deg=270))["surf_score"], 0)

    def test_stale_forecast_is_not_ranked(self):
        result = rate(self.spot, forecast(status="stale"))
        self.assertIsNone(result["surf_score"])
        self.assertIsNone(result["wind_score"])

    def test_stale_waves_allow_only_wind_rating(self):
        result = rate(self.spot, forecast(wave_status="stale"))
        self.assertIsNone(result["surf_score"])
        self.assertIsNotNone(result["wind_score"])


class ParserTests(unittest.TestCase):
    def test_grid_gusts_honor_units_and_intervals(self):
        now = utcnow().replace(minute=0, second=0, microsecond=0)
        rows = fixture_rows(now)
        for row in rows:
            row["gust_kts"] = None
        add_nws_gusts(
            rows,
            {
                "properties": {
                    "windGust": {
                        "uom": "wmoUnit:km_h-1",
                        "values": [
                            {"validTime": stamp(now) + "/PT2H", "value": 37.04},
                            {"validTime": stamp(now + timedelta(hours=2)) + "/PT1H", "value": None},
                        ],
                    }
                }
            },
        )
        self.assertEqual(rows[0]["gust_kts"], 20)
        self.assertEqual(rows[1]["gust_kts"], 20)
        self.assertIsNone(rows[2]["gust_kts"])

    def test_ndbc_each_field_keeps_its_own_time(self):
        now = utcnow().replace(second=0, microsecond=0)
        header = "#YY MM DD hh mm WDIR WSPD GST WVHT DPD MWD WTMP\n#yr mo dy hr mn degT m/s m/s m sec degT degC\n"
        raw = header + now.strftime("%Y %m %d %H %M") + " 30 8 10 MM MM MM 18\n"
        raw += (now - timedelta(minutes=10)).strftime("%Y %m %d %H %M") + " 45 9 11 1.0 5 32 18.1\n"
        data = parse_ndbc(raw, now)["measurements"]
        self.assertAlmostEqual(data["wind_kts"]["value"], 15.551, places=3)
        self.assertEqual(data["wave_height_m"]["value"], 1)
        self.assertNotEqual(data["wind_kts"]["time"], data["wave_height_m"]["time"])

    def test_ndbc_bad_future_and_old_rows_do_not_become_readings(self):
        now = utcnow()
        raw = "#YY MM DD hh mm WDIR WSPD GST WVHT DPD MWD WTMP\n"
        raw += (now + timedelta(days=1)).strftime("%Y %m %d %H %M") + " 0 8 10 1 5 30 18\n"
        raw += (now - timedelta(days=2)).strftime("%Y %m %d %H %M") + " 0 8 10 1 5 30 18\n"
        raw += now.strftime("%Y %m %d %H %M") + " MM NaN -1 99 99 999 999\n"
        self.assertTrue(all(v is None for v in parse_ndbc(raw, now)["measurements"].values()))

    def test_ndbc_calm_and_north_are_real_values(self):
        now = utcnow()
        raw = (
            "#YY MM DD hh mm WDIR WSPD GST WVHT DPD MWD WTMP\n"
            + now.strftime("%Y %m %d %H %M")
            + " 0 0 0 0 MM MM 0\n"
        )
        data = parse_ndbc(raw, now)["measurements"]
        self.assertEqual(data["wind_kts"]["value"], 0)
        self.assertEqual(data["wind_dir_deg"]["value"], 0)
        self.assertEqual(data["water_temp_c"]["value"], 0)

    def test_wind_parsing_preserves_missing_fields_and_units(self):
        self.assertIsNone(speed(None))
        self.assertIsNone(direction("VRB"))
        self.assertIsNone(direction(None))
        self.assertAlmostEqual(speed("10 to 20 mph"), 13.03464)
        self.assertEqual(speed("10 knots"), 10)
        self.assertIsNone(speed("10 unknown"))
        self.assertEqual(direction("NNE"), 22.5)

    def test_nws_does_not_invent_gusts(self):
        now = utcnow()
        data = {
            "properties": {
                "periods": [
                    {
                        "startTime": stamp(now),
                        "endTime": stamp(now + timedelta(hours=1)),
                        "windSpeed": "15 mph",
                        "windDirection": "E",
                    }
                ]
            }
        }
        self.assertIsNone(parse_nws(data)[0]["gust_kts"])

    def test_nws_rejects_non_hourly_fallback(self):
        now = utcnow()
        data = {
            "properties": {
                "periods": [
                    {
                        "startTime": stamp(now),
                        "endTime": stamp(now + timedelta(hours=12)),
                        "windSpeed": "15 mph",
                        "windDirection": "E",
                    }
                ]
            }
        }
        with self.assertRaises(ValueError):
            parse_nws(data)


class CacheTests(Base):
    def test_nws_failure_uses_labeled_wind_fallback(self):
        now = utcnow().replace(minute=0, second=0, microsecond=0)

        def respond(request):
            if request.url.host == "api.weather.gov":
                return httpx.Response(503)
            return httpx.Response(
                200,
                json={
                    "hourly": {
                        "time": [stamp(now)],
                        "wind_speed_10m": [16],
                        "wind_direction_10m": [45],
                        "wind_gusts_10m": [22],
                    }
                },
            )

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                return await WeatherStore().fetch_wind(client, self.spot)

        result = asyncio.run(run())
        self.assertEqual(result["source"], "Open-Meteo")
        self.assertEqual(result["rows"][0]["wind_kts"], 16)

    def test_far_away_marine_grid_is_rejected(self):
        def respond(request):
            return httpx.Response(200, json={"latitude": 10, "longitude": 20})

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                await WeatherStore().fetch_waves(client, self.spot)

        with self.assertRaises(ValueError):
            asyncio.run(run())

    def test_refresh_workflows_are_bounded(self):
        store = WeatherStore()
        active = 0
        peak = 0

        async def fetch(*args):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.001)
            active -= 1
            return {"rows": []}

        store.fetch_wind = fetch
        store.fetch_waves = fetch
        store.fetch_buoy = fetch
        asyncio.run(store.refresh(self.spots))
        self.assertLessEqual(peak, 4)
        self.assertGreater(peak, 1)

    def test_selects_actual_forecast_interval_not_nearest(self):
        store = WeatherStore()
        now = utcnow().replace(minute=0, second=0, microsecond=0)
        store.records["wind:spot"] = {
            "rows": fixture_rows(now),
            "fetched_at": stamp(now),
            "source": "NWS",
        }
        self.assertEqual(store.forecast("spot", now + timedelta(hours=3))["wind_kts"], 18)
        self.assertIsNone(store.forecast("spot", now - timedelta(hours=1))["wind_kts"])
        self.assertIsNone(store.forecast("spot", now + timedelta(hours=60))["wind_kts"])

    def test_stale_cache_keeps_original_time(self):
        store = WeatherStore()
        now = utcnow()
        old = stamp(now - timedelta(hours=5))
        store.records["wind:spot"] = {"rows": fixture_rows(now), "fetched_at": old, "source": "NWS"}
        result = store.forecast("spot", now)
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["fetched_at"], old)

    def test_missing_cache_is_unavailable(self):
        result = WeatherStore().forecast("spot", utcnow())
        self.assertIsNone(result["wind_kts"])
        self.assertEqual(result["status"], "unavailable")

    def test_demo_does_not_overwrite_live_cache(self):
        store = WeatherStore()
        store.save("wind:live", {"value": "actual"})
        store.load_demo(self.spots)
        fresh = WeatherStore()
        fresh.load()
        self.assertEqual(fresh.get("wind:live"), {"value": "actual"})
        self.assertIsNone(fresh.get("wind:sheboygan-elbow"))

    def test_refresh_reuses_recent_cache(self):
        store = WeatherStore()
        store.fetch_wind = AsyncMock(return_value={"rows": fixture_rows(), "source": "NWS"})
        store.fetch_waves = AsyncMock(return_value={"rows": []})
        store.fetch_buoy = AsyncMock(return_value={"measurements": {}, "history": []})

        async def run():
            await store.refresh(self.spots)
            await store.refresh(self.spots)

        asyncio.run(run())
        self.assertEqual(store.fetch_wind.await_count, 6)
        self.assertEqual(store.fetch_buoy.await_count, 4)

    def test_provider_failure_keeps_last_good_readings(self):
        store = WeatherStore()
        old = stamp(utcnow() - timedelta(minutes=30))
        store.save(
            f"wind:{self.spot.id}",
            {"rows": fixture_rows(), "source": "NWS", "fetched_at": old, "attempted_at": old},
        )
        store.fetch_wind = AsyncMock(side_effect=httpx.ConnectError("offline"))
        store.fetch_waves = AsyncMock(side_effect=httpx.ConnectError("offline"))
        store.fetch_buoy = AsyncMock(side_effect=httpx.ConnectError("offline"))
        asyncio.run(store.refresh([self.spot]))
        result = store.forecast(self.spot.id, utcnow())
        self.assertEqual(result["status"], "stale")
        self.assertIsNotNone(result["wind_kts"])
        self.assertEqual(result["fetched_at"], old)

    def test_observation_freshness_is_independent_of_forecast_selection(self):
        store = WeatherStore()
        old = stamp(utcnow() - timedelta(hours=3))
        store.records["buoy:45002"] = {
            "measurements": {
                "wind_kts": {"value": 20, "time": stamp(utcnow())},
                "wave_height_m": {"value": 1, "time": old},
            }
        }
        station = store.stations()[0]
        self.assertEqual(station["status"], "fresh")
        self.assertEqual(station["measurements"]["wave_height_m"]["status"], "stale")
        self.assertEqual(station["measurements"]["wave_height_m"]["time"], old)


class RouteTests(Base):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app)

    def test_restart_seed_preserves_edited_notes(self):
        with engine.begin() as db:
            db.execute(
                text(
                    "UPDATE spots SET notes='Good cleanup',notes_edited_by='Zach',notes_edited_at='2026-09-20T12:00:00+00:00' WHERE id='sheboygan-elbow'"
                )
            )
        seed_spots_if_empty()
        spot = next(s for s in get_all_spots() if s.id == self.spot.id)
        self.assertEqual(spot.notes, "Good cleanup")
        self.assertEqual(spot.notes_edited_by, "Zach")

    def test_pages_render_without_weather_or_external_requests(self):
        with patch(
            "httpx.AsyncClient.get", side_effect=AssertionError("Page requested external data")
        ):
            for path in (
                "/",
                "/?h=6",
                "/buoys",
                "/crew",
                "/about",
                "/api/status",
                *[f"/spots/{s.id}" for s in self.spots],
            ):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, path)
        self.assertIn("Forecast unavailable", self.client.get("/").text)

    def test_demo_pages_are_explicit(self):
        weather.load_demo(self.spots)
        for path in ("/", "/buoys", f"/spots/{self.spot.id}"):
            self.assertIn("DEMO MODE", self.client.get(path).text)

    def test_existing_notes_are_escaped(self):
        with patch.dict(os.environ, {"NOTES_ADMIN_PASSWORD": "test-password"}):
            response = self.client.post(
                "/spot-notes",
                data={
                    "spot_id": self.spot.id,
                    "notes": '<img src=x onerror="alert(1)">',
                    "editor_name": "<script>bad</script>",
                    "password": "test-password",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("&lt;img", response.text)
        self.assertNotIn("<img src=x", response.text)
        self.assertNotIn("<script>bad</script>", response.text)

    def test_note_password_failure_does_not_write(self):
        original = self.spot.notes
        with patch.dict(os.environ, {"NOTES_ADMIN_PASSWORD": "right"}):
            response = self.client.post(
                "/spot-notes",
                data={
                    "spot_id": self.spot.id,
                    "notes": "changed",
                    "editor_name": "test",
                    "password": "wrong",
                },
            )
        self.assertIn("password didn’t match", response.text)
        self.assertEqual(next(s for s in get_all_spots() if s.id == self.spot.id).notes, original)

    def test_checkin_token_is_fragment_only_and_delete_is_post(self):
        response = self.client.post(
            "/checkins",
            data={
                "user_id": "Surfer",
                "spot_id": self.spot.id,
                "arrive_start": "10:00",
                "arrive_end": "12:00",
                "note": "Longboard",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        url = urlsplit(response.headers["location"])
        self.assertEqual(url.query, "")
        values = parse_qs(url.fragment)
        ident, token = values["checkin_id"][0], values["token"][0]
        self.assertNotIn(token, self.client.get("/crew").text)
        self.assertEqual(self.client.get("/checkins/delete").status_code, 405)
        self.client.post("/checkins/delete", data={"id": ident, "token": "wrong"})
        self.assertIn("Surfer", self.client.get("/crew").text)
        self.client.post("/checkins/delete", data={"id": ident, "token": token})
        self.assertNotIn("Surfer", self.client.get("/crew").text)

    def test_bad_checkin_input_is_rejected(self):
        for data in (
            {"spot_id": "missing"},
            {"arrive_end": "08:00"},
            {"arrive_start": "nonsense"},
            {"user_id": " "},
        ):
            response = self.client.post(
                "/checkins",
                data={
                    "user_id": "Surfer",
                    "spot_id": self.spot.id,
                    "arrive_start": "10:00",
                    "arrive_end": "12:00",
                    **data,
                },
            )
            self.assertIn(response.status_code, (404, 422))

    def test_old_checkins_hidden_at_local_day_boundary(self):
        with engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO checkins (user_id,spot_id,created_at) VALUES ('Yesterday',:spot,'2020-01-01 00:00:00')"
                ),
                {"spot": self.spot.id},
            )
        self.assertNotIn("Yesterday", self.client.get("/crew").text)

    def test_invalid_hour_falls_back_without_crashing(self):
        for h in ("bad", "-1", "999999"):
            self.assertEqual(self.client.get("/?h=" + h).status_code, 200)

    def test_unknown_spot_and_camera_return_404(self):
        self.assertEqual(self.client.get("/spots/missing").status_code, 404)
        self.assertEqual(self.client.get("/camera/missing").status_code, 404)

    def test_camera_uses_one_connection_and_closes_it(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(
                200,
                content=b"test-frame",
                headers={"content-type": "multipart/x-mixed-replace; boundary=frame"},
            )

        upstream = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch("app.routers.ui.httpx.AsyncClient", return_value=upstream):
            response = self.client.get("/camera/two-rivers")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"test-frame")
        self.assertEqual(len(requests), 1)
        self.assertTrue(upstream.is_closed)

    def test_camera_upstream_error_is_handled(self):
        upstream = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(503))
        )
        with patch("app.routers.ui.httpx.AsyncClient", return_value=upstream):
            self.assertEqual(self.client.get("/camera/two-rivers").status_code, 503)
        self.assertTrue(upstream.is_closed)


if __name__ == "__main__":
    unittest.main()
