"""Wind color thresholds and missing-data presentation."""

import re
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from test_app import Base

from app.main import app
from app.services.weather import stamp, utcnow, weather
from app.services.wind_style import WIND_LEGEND, wind_style


class WindStyleTests(unittest.TestCase):
    def test_thresholds_use_fixed_bands(self):
        for index, band in enumerate(WIND_LEGEND):
            with self.subTest(band=band["band"]):
                style = wind_style(band["min_kts"])
                self.assertEqual(style["band"], band["band"])
                self.assertEqual(style["color"], band["color"])
                self.assertTrue(style["available"])
                if index:
                    below = wind_style(band["min_kts"] - 0.01)
                    self.assertEqual(below["band"], WIND_LEGEND[index - 1]["band"])

    def test_calm_is_distinct_from_missing(self):
        calm, missing = wind_style(0), wind_style(None)
        self.assertTrue(calm["available"])
        self.assertEqual(calm["band"], "lavender")
        self.assertEqual(calm["height"], 0)
        self.assertFalse(missing["available"])
        self.assertEqual(missing["band"], "unknown")
        self.assertEqual(missing["height"], 0)

    def test_invalid_values_have_no_color_band_or_bar(self):
        for value in [-1, -0.01, float("nan"), float("inf"), True, False, "bad", {}]:
            with self.subTest(value=value):
                style = wind_style(value)
                self.assertFalse(style["available"])
                self.assertEqual(style["band"], "unknown")
                self.assertEqual(style["height"], 0)

    def test_bar_height_preserves_proportions_and_caps_at_40_knots(self):
        for value, expected in [(0, 0), (10, 25), (20, 50), (40, 100), (75, 100)]:
            with self.subTest(knots=value):
                self.assertEqual(wind_style(value)["height"], expected)
        self.assertEqual(wind_style(75)["band"], "coral")

    def test_wind_text_has_accessible_contrast_on_its_tint(self):
        def luminance(hex_color):
            channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
            return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

        for band in (*WIND_LEGEND, wind_style(None)):
            with self.subTest(band=band["band"]):
                ratio = (luminance(band["color"]) + 0.05) / (luminance(band["tint"]) + 0.05)
                self.assertGreaterEqual(ratio, 4.5)


class WindRenderTests(Base):
    def test_hourly_colors_match_displayed_rounded_values_and_preserve_missing(self):
        start = utcnow().replace(minute=0, second=0, microsecond=0)
        weather.records[f"wind:{self.spot.id}"] = {
            "fetched_at": stamp(utcnow()),
            "source": "NWS",
            "rows": [
                {
                    "time": stamp(start + timedelta(hours=i)),
                    "end": stamp(start + timedelta(hours=i + 1)),
                    "wind_kts": wind,
                    "gust_kts": gust,
                    "wind_dir_deg": 180,
                }
                for i, (wind, gust) in enumerate([(14.8, 19.6), (19.6, 14.8), (0, 0), (None, None)])
            ],
        }
        with (
            patch("app.routers.ui.utcnow", return_value=start),
            patch("httpx.AsyncClient.get", side_effect=AssertionError("External request")),
        ):
            response = TestClient(app).get(f"/spots/{self.spot.id}?h=0")
        self.assertEqual(response.status_code, 200)
        cells = re.findall(
            r'<td class="(wind-cell|gust-cell) ([^"]*)" style="([^"]*)">'
            r"<span[^>]*>([^<]*)</span>",
            response.text,
        )
        for row, expected in [
            ("wind-cell", [("15", "teal"), ("20", "green"), ("0", "lavender"), ("—", "unknown")]),
            ("gust-cell", [("20", "green"), ("15", "teal"), ("0", "lavender"), ("—", "unknown")]),
        ]:
            actual = [
                (classes, style, value) for kind, classes, style, value in cells if kind == row
            ]
            self.assertEqual(len(actual), 48)
            for (classes, style, value), (displayed, band) in zip(actual, expected):
                with self.subTest(row=row, value=displayed):
                    self.assertEqual(value, displayed)
                    self.assertIn("wind-band-" + band, classes.split())
                    color = wind_style(None if displayed == "—" else int(displayed))["color"]
                    self.assertIn("--wind-color:" + color, style)
                    if row == "wind-cell" and displayed in {"0", "—"}:
                        self.assertIn("--wind-bar:0", style)
