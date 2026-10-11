"""Hourly browsing uses cached forecasts and preserves their data confidence."""

import gzip
import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from starlette.requests import Request
from test_app import Base, fixture_rows

from app.main import app
from app.routers import ui
from app.routers.ui import hours
from app.services.weather import parse_time, stamp, weather
from app.services.wind_style import wind_style


class ForecastSliderTests(Base):
    start = datetime(2026, 10, 11, 4, tzinfo=timezone.utc)  # Saturday, 11 PM CDT.

    def seed_forecasts(self, *, wind_age=0, wave_age=0):
        for spot in self.spots:
            weather.records[f"wind:{spot.id}"] = {
                "rows": fixture_rows(self.start),
                "fetched_at": stamp(self.start - timedelta(hours=wind_age)),
                "source": "NWS",
            }
            weather.records[f"waves:{spot.id}"] = {
                "rows": [
                    {
                        "time": stamp(self.start + timedelta(hours=i)),
                        "end": stamp(self.start + timedelta(hours=i + 1)),
                        "wave_height_m": 1 + i / 100,
                        "wave_period_s": 5,
                        "wave_dir_deg": 90,
                    }
                    for i in range(49)
                ],
                "fetched_at": stamp(self.start - timedelta(hours=wave_age)),
                "source": "Open-Meteo Marine",
            }
            weather.records[f"conditions:{spot.id}"] = {
                "rows": [
                    {
                        "time": stamp(self.start + timedelta(hours=i)),
                        "end": stamp(self.start + timedelta(hours=i + 1)),
                        "temperature_f": 55 + i,
                        "description": "Clear night" if i < 8 else "Sunny",
                        "icon": "moon" if i < 8 else "sun",
                    }
                    for i in range(49)
                ],
                "days": {
                    "2026-10-10": {
                        "sunrise": "2026-10-10T11:57:00+00:00",
                        "sunset": "2026-10-11T00:16:00+00:00",
                    },
                    "2026-10-11": {
                        "sunrise": "2026-10-11T11:58:00+00:00",
                        "sunset": "2026-10-12T00:14:00+00:00",
                    },
                    "2026-10-12": {
                        "sunrise": "2026-10-12T11:59:00+00:00",
                        "sunset": "2026-10-13T00:12:00+00:00",
                    },
                },
                "fetched_at": stamp(self.start),
                "source": "Open-Meteo",
            }

    def request_page(self, path, *, headers=None, raw=False):
        raw_body = None
        with (
            patch("app.routers.ui.utcnow", return_value=self.start),
            patch("app.services.weather.utcnow", return_value=self.start),
            patch("app.services.conditions.utcnow", return_value=self.start),
            patch("httpx.AsyncClient.get", side_effect=AssertionError("External request")),
        ):
            client = TestClient(app)
            if raw:
                with client.stream("GET", path, headers=headers) as response:
                    raw_body = b"".join(response.iter_raw())
            else:
                response = client.get(path, headers=headers)
        self.assertEqual(response.status_code, 200)
        return response, raw_body

    def page(self, path):
        return self.request_page(path)[0].text

    def timeline(self, html):
        match = re.search(r'<script\b[^>]*id="forecast-timeline"[^>]*>(.*?)</script>', html, re.S)
        self.assertIsNotNone(match, "Page must supply cached snapshots for instant hourly browsing")
        return json.loads(match.group(1))

    def test_every_whole_hour_is_selectable_including_nonpreset_hours(self):
        for hour in (0, 1, 2, 8, 25, 47, 48):
            with self.subTest(hour=hour):
                request = Request({"type": "http", "query_string": f"h={hour}".encode()})
                self.assertEqual(hours(request), hour)

    def test_invalid_hour_falls_back_to_now(self):
        for value in ("", "nope", "2.5", "-1", "49", "999999", "<script>alert(1)</script>"):
            with self.subTest(value=value):
                query = urlencode({"h": value}).encode()
                self.assertEqual(hours(Request({"type": "http", "query_string": query})), 0)
        self.assertEqual(hours(Request({"type": "http", "query_string": b""})), 0)

    def test_detail_timeline_and_table_reach_the_same_48_hour_endpoint(self):
        self.seed_forecasts()
        page = self.page(f"/spots/{self.spot.id}?h=48")
        timeline = self.timeline(page)
        self.assertEqual(len(timeline), 49)
        for hour, snapshot in enumerate(timeline):
            self.assertEqual(parse_time(snapshot["at"]), self.start + timedelta(hours=hour))
            self.assertTrue(snapshot["caption"])
            self.assertTrue(snapshot["local_label"])
        selected = timeline[48]
        self.assertIn(selected["conditions_html"], page)
        self.assertIn(selected["rating_html"], page)
        self.assertIn(stamp(self.start + timedelta(hours=48)), page)
        self.assertEqual(page.count('class="selected-hour-label">'), 1)
        self.assertRegex(page, r'data-forecast-hour="48"[^>]*aria-pressed="true"')
        self.assertEqual(len(re.findall(r'<td class="wind-cell\b', page)), 49)

    def test_home_snapshots_update_all_cards_and_the_map_from_the_same_hour(self):
        self.seed_forecasts()
        timeline = self.timeline(self.page("/?h=8"))
        self.assertEqual(len(timeline), 49)
        expected_ids = {spot.id for spot in self.spots}
        for hour in (0, 2, 8, 47, 48):
            snapshot = timeline[hour]
            self.assertEqual(parse_time(snapshot["at"]), self.start + timedelta(hours=hour))
            self.assertEqual({item["id"] for item in snapshot["items"]}, expected_ids)
            self.assertEqual({item["id"] for item in snapshot["map_spots"]}, expected_ids)
            for item in snapshot["items"]:
                self.assertIn(f"?h={hour}", item["html"])
                self.assertIsNotNone(item["wind_score"])
                self.assertIsNotNone(item["surf_score"])
            for marker in snapshot["map_spots"]:
                self.assertEqual(marker["wind"], 15 + hour)
                self.assertIsNotNone(marker["score"])

    def test_temperature_and_daylight_follow_local_midnight_when_scrubbing(self):
        self.seed_forecasts()
        timeline = self.timeline(self.page(f"/spots/{self.spot.id}?h=2"))
        before, after = timeline[0], timeline[2]
        self.assertIn("Sat", before["local_label"])
        self.assertIn("Sun", after["local_label"])
        self.assertIn("11:57:00", before["conditions_html"])
        self.assertIn("00:16:00", before["conditions_html"])
        self.assertIn("11:58:00", after["conditions_html"])
        self.assertIn("00:14:00", after["conditions_html"])
        self.assertNotIn("11:57:00", after["conditions_html"])
        self.assertIn("55", before["conditions_html"])
        self.assertIn("57", after["conditions_html"])

    def test_missing_hours_remain_unavailable_and_are_distinct_from_real_calm(self):
        self.seed_forecasts()
        for spot in self.spots:
            rows = weather.records[f"wind:{spot.id}"]["rows"]
            rows[0].update(wind_kts=0, gust_kts=0)
            del rows[1:]
        detail = self.timeline(self.page(f"/spots/{self.spot.id}?h=2"))
        self.assertIn("--wind-color:" + wind_style(0)["color"], detail[0]["conditions_html"])
        self.assertIn("Waiting for a usable wind forecast", detail[2]["rating_html"])
        self.assertIn('aria-label="Direction unavailable"', detail[2]["conditions_html"])
        home = self.timeline(self.page("/?h=2"))
        for item in home[0]["items"]:
            self.assertEqual(item["wind_score"], 0)
        for hour in (2, 8, 48):
            for item in home[hour]["items"]:
                self.assertIsNone(item["wind_score"])
                self.assertIsNone(item["surf_score"])
                self.assertIn("Forecast unavailable", item["html"])
            for marker in home[hour]["map_spots"]:
                self.assertIsNone(marker["wind"])
                self.assertIsNone(marker["score"])

    def test_stale_forecasts_keep_values_but_suppress_ratings_in_every_snapshot(self):
        self.seed_forecasts(wind_age=5)
        detail = self.timeline(self.page(f"/spots/{self.spot.id}?h=8"))
        home = self.timeline(self.page("/?h=8"))
        for hour in (0, 8, 48):
            self.assertIn("Stale forecast", detail[hour]["rating_html"])
            self.assertIn("An older forecast is shown for context", detail[hour]["rating_html"])
            for item in home[hour]["items"]:
                self.assertIsNone(item["wind_score"])
                self.assertIsNone(item["surf_score"])
                self.assertIn("stale", item["html"])
            for marker in home[hour]["map_spots"]:
                self.assertEqual(marker["wind"], 15 + hour)
                self.assertIsNone(marker["score"])

    def test_stale_waves_retain_wind_setup_without_inventing_a_surf_rating(self):
        self.seed_forecasts(wave_age=5)
        timeline = self.timeline(self.page("/?h=47"))
        for hour in (0, 8, 47, 48):
            for item in timeline[hour]["items"]:
                self.assertIsNotNone(item["wind_score"])
                self.assertIsNone(item["surf_score"])
                self.assertIn("Wind setup", item["html"])
                self.assertIn("stale", item["html"])

    def test_compressed_hourly_pages_deliver_the_same_forecasts_with_correct_headers(self):
        self.seed_forecasts()
        for path in ("/?h=8", f"/spots/{self.spot.id}?h=48"):
            with self.subTest(path=path):
                identity, _ = self.request_page(path, headers={"Accept-Encoding": "identity"})
                compressed, body = self.request_page(
                    path, headers={"Accept-Encoding": "gzip"}, raw=True
                )
                self.assertNotIn("Content-Encoding", identity.headers)
                self.assertEqual(compressed.headers["Content-Encoding"], "gzip")
                self.assertEqual(int(compressed.headers["Content-Length"]), len(body))
                self.assertIn("Accept-Encoding", compressed.headers["Vary"])
                self.assertIn("Accept-Encoding", identity.headers["Vary"])
                self.assertEqual(gzip.decompress(body), identity.content)
                self.assertLess(len(body), len(identity.content))
                self.assertEqual(compressed.context["h"], identity.context["h"])
                self.assertEqual(len(compressed.context["forecast_timeline"]), 49)

    def test_explicit_gzip_refusal_takes_precedence_over_an_accepted_wildcard(self):
        self.seed_forecasts()
        for path in ("/?h=2", f"/spots/{self.spot.id}?h=47"):
            with self.subTest(path=path):
                identity, _ = self.request_page(path, headers={"Accept-Encoding": "identity"})
                refused, body = self.request_page(
                    path, headers={"Accept-Encoding": "gzip;q=0, *;q=1"}, raw=True
                )
                self.assertNotIn("Content-Encoding", refused.headers)
                self.assertIn("Accept-Encoding", refused.headers["Vary"])
                self.assertEqual(int(refused.headers["Content-Length"]), len(body))
                self.assertEqual(body, identity.content)

    def test_daylight_events_use_exact_times_and_skip_duplicates_and_bad_cache_values(self):
        sunrise = self.start + timedelta(hours=7, minutes=58)
        end = self.start + timedelta(hours=48)
        weather.records[f"conditions:{self.spot.id}"] = {
            "days": {
                "last": {"sunrise": stamp(sunrise), "sunset": stamp(end)},
                "first": {"sunrise": stamp(self.start), "sunset": None},
                "repeat": {"sunrise": stamp(self.start), "sunset": stamp(end)},
                "outside": {
                    "sunrise": stamp(self.start - timedelta(minutes=1)),
                    "sunset": stamp(end + timedelta(minutes=1)),
                },
                "bad": {"sunrise": "not a timestamp", "sunset": ""},
            },
        }
        events = ui.daylight_events(self.spot, self.start)
        self.assertEqual(
            [(event["kind"], parse_time(event["time"])) for event in events],
            [("sunrise", self.start), ("sunrise", sunrise), ("sunset", end)],
        )
        self.assertEqual(events[0]["position"], 0)
        self.assertAlmostEqual(events[1]["position"], (7 + 58 / 60) / 48 * 100)
        self.assertEqual(events[2]["position"], 100)
        self.assertIn("6:58", events[1]["label"])
        self.assertIn(self.spot.name, events[1]["title"])
        weather.records.clear()
        self.assertEqual(ui.daylight_events(self.spot, self.start), [])

    def test_daylight_positions_follow_elapsed_hours_across_the_dst_clock_change(self):
        start = datetime(2026, 11, 1, 5, tzinfo=timezone.utc)  # Midnight CDT before fallback.
        weather.records[f"conditions:{self.spot.id}"] = {
            "days": {
                "2026-11-01": {
                    "sunrise": "2026-11-01T06:29:00-06:00",
                    "sunset": "2026-11-01T16:43:00-06:00",
                },
            },
        }
        sunrise, sunset = ui.daylight_events(self.spot, start)
        self.assertEqual(parse_time(sunrise["time"]), start + timedelta(hours=7, minutes=29))
        self.assertAlmostEqual(sunrise["position"], (7 + 29 / 60) / 48 * 100)
        self.assertAlmostEqual(sunset["position"], (17 + 43 / 60) / 48 * 100)
        self.assertIn("6:29", sunrise["label"])
        self.assertIn("CST", sunrise["title"])
        self.assertIn("4:43", sunset["label"])
        self.assertIn("CST", sunset["title"])

    def test_daylight_markers_use_the_page_location_and_keep_the_exact_cached_minute(self):
        class MarkerParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.markers = []

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if "forecast-daylight-marker" in attrs.get("class", "").split():
                    self.markers.append(attrs)

        self.seed_forecasts()
        first_spot = self.spots[0]
        self.assertEqual(first_spot.id, "north-pier-two-rivers")
        detail_sunrise = self.start + timedelta(hours=8, minutes=7)
        weather.records[f"conditions:{self.spot.id}"]["days"]["2026-10-11"]["sunrise"] = stamp(
            detail_sunrise
        )
        for path, spot, expected_time in (
            ("/?h=8", first_spot, self.start + timedelta(hours=7, minutes=58)),
            (f"/spots/{self.spot.id}?h=2", self.spot, detail_sunrise),
        ):
            with self.subTest(path=path):
                parser = MarkerParser()
                parser.feed(self.page(path))
                self.assertEqual(len(parser.markers), 4)
                marker = parser.markers[0]
                self.assertEqual(marker["data-daylight-kind"], "sunrise")
                self.assertEqual(parse_time(marker["data-daylight-time"]), expected_time)
                elapsed = (expected_time - self.start).total_seconds() / 3600
                self.assertAlmostEqual(float(marker["data-daylight-position"]), elapsed / 48 * 100)
                self.assertIn(spot.name, marker["title"])
