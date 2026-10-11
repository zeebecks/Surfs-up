"""A fixed, dark-theme wind speed scale shared by forecasts and their legend."""

import math

# Keep thresholds fixed across locations and hours so the colors remain comparable.
WIND_LEGEND = (
    {
        "band": "lavender",
        "class_name": "wind-band-lavender",
        "min_kts": 0,
        "max_kts": 5,
        "label": "0–4 kt",
        "color": "#B6A4E9",
        "tint": "#29273A",
    },
    {
        "band": "light-blue",
        "class_name": "wind-band-light-blue",
        "min_kts": 5,
        "max_kts": 10,
        "label": "5–9 kt",
        "color": "#A1D5EF",
        "tint": "#20313C",
    },
    {
        "band": "blue",
        "class_name": "wind-band-blue",
        "min_kts": 10,
        "max_kts": 15,
        "label": "10–14 kt",
        "color": "#79B9EB",
        "tint": "#1D3041",
    },
    {
        "band": "teal",
        "class_name": "wind-band-teal",
        "min_kts": 15,
        "max_kts": 20,
        "label": "15–19 kt",
        "color": "#75D0CD",
        "tint": "#1D373A",
    },
    {
        "band": "green",
        "class_name": "wind-band-green",
        "min_kts": 20,
        "max_kts": 25,
        "label": "20–24 kt",
        "color": "#9ACF9F",
        "tint": "#28382F",
    },
    {
        "band": "yellow",
        "class_name": "wind-band-yellow",
        "min_kts": 25,
        "max_kts": 30,
        "label": "25–29 kt",
        "color": "#E6CE88",
        "tint": "#3A3526",
    },
    {
        "band": "orange",
        "class_name": "wind-band-orange",
        "min_kts": 30,
        "max_kts": 35,
        "label": "30–34 kt",
        "color": "#E7AF79",
        "tint": "#3C3028",
    },
    {
        "band": "coral",
        "class_name": "wind-band-coral",
        "min_kts": 35,
        "max_kts": None,
        "label": "35+ kt",
        "color": "#E69D92",
        "tint": "#3D2A2B",
    },
)


def wind_style(value):
    """Return presentation metadata; missing values never masquerade as calm wind."""
    unknown = {
        "band": "unknown",
        "class_name": "wind-band-unknown",
        "color": "#9AAEB3",
        "tint": "#1B2B31",
        "height": 0,
        "label": "Wind unavailable",
        "available": False,
    }
    if value is None or isinstance(value, bool):
        return unknown
    try:
        knots = float(value)
    except (TypeError, ValueError, OverflowError):
        return unknown
    if not math.isfinite(knots) or knots < 0:
        return unknown

    band = next(b for b in WIND_LEGEND if b["max_kts"] is None or knots < b["max_kts"])
    return {
        **band,
        "height": min(knots / 40 * 100, 100),
        "available": True,
    }
