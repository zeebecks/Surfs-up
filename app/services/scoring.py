"""Version 2: explainable heuristics, deliberately separate from data confidence."""

import math

VERSION = "2.0-experimental"
CARDINALS = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}


def ang_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


def bucket(score):
    if score is None:
        return "unknown"
    return (
        "poor"
        if score < 35
        else "mixed"
        if score < 60
        else "promising"
        if score < 80
        else "favorable"
    )


def rate(spot, forecast):
    wind, direction = forecast.get("wind_kts"), forecast.get("wind_dir_deg")
    result = dict(
        wind_score=None,
        surf_score=None,
        bucket="unknown",
        confidence="Unavailable",
        reason="Waiting for a usable wind forecast.",
        factors=[],
        version=VERSION,
    )
    if forecast.get("status") == "stale":
        result.update(
            confidence="Stale forecast",
            reason="An older forecast is shown for context. Ratings resume when the source updates.",
        )
        return result
    if wind is None or direction is None or not all(math.isfinite(v) for v in (wind, direction)):
        return result
    preferred = [CARDINALS[c] for c in spot.fetch_hints if c in CARDINALS]
    alignment = max(0, 1 - min((ang_diff(direction, d) for d in preferred), default=180) / 100)
    strength = min(1, wind / max(1, spot.min_wind_kts))
    # A calm or weak breeze cannot build a high score solely on direction.
    strength = strength**1.7
    over = max(0, wind - spot.max_wind_kts)
    strength *= max(0.25, 1 - over / 30)
    gust = forecast.get("gust_kts")
    stability = max(0.65, 1 - max(0, gust - wind) / 60) if gust is not None else 0.85
    wind_score = round(100 * alignment * strength * stability)
    onshore_angle = ang_diff(direction, spot.shoreline_orientation)
    surface = (
        "onshore" if onshore_angle < 45 else "cross-shore" if onshore_angle < 135 else "offshore"
    )
    result.update(
        wind_score=wind_score,
        bucket=bucket(wind_score),
        confidence="Wind model only",
        reason="Wind setup estimates wave-building potential, not confirmed surf.",
        factors=[
            {
                "name": "Wind direction",
                "value": f"{surface.capitalize()} · preferred fetch: {', '.join(spot.fetch_hints)}",
            },
            {
                "name": "Wind strength",
                "value": f"{wind:.0f} kt · configured building range {spot.min_wind_kts}–{spot.max_wind_kts} kt",
            },
        ],
    )
    wave = forecast.get("wave_height_m")
    period = forecast.get("wave_period_s")
    wave_dir = forecast.get("wave_dir_deg")
    if (
        wave is None
        or period is None
        or wave_dir is None
        or forecast.get("wave_status") not in {"fresh", "demo"}
    ):
        return result
    # Open-water wave height is evidence of energy, not a prediction of breaking height.
    energy = min(1, max(0, (wave - 0.15) / 0.85))
    period_quality = max(0.3, min(1, (period - 1.5) / 4))
    exposure = max(0, math.cos(math.radians(ang_diff(wave_dir, spot.shoreline_orientation)))) ** 0.5
    surface_quality = (
        max(0.25, 1 - wind / 35)
        if surface == "onshore"
        else max(0.35, 1 - wind / 45)
        if surface == "cross-shore"
        else max(0.4, 1 - max(0, wind - 12) / 35)
    )
    excessive = max(0.3, 1 - max(0, wave - 2.5) / 3)
    surf_score = round(
        100 * energy * exposure * (0.55 * period_quality + 0.45 * surface_quality) * excessive
    )
    result.update(
        surf_score=surf_score,
        bucket=bucket(surf_score),
        confidence="Model estimate",
        reason=f"{wave * 3.28084:.1f} ft modeled waves at {period:.0f}s with {surface} wind. Local shelter and breaking waves may differ.",
    )
    result["factors"].extend(
        [
            {
                "name": "Wave energy",
                "value": f"{wave * 3.28084:.1f} ft at {period:.1f}s · modeled offshore",
            },
            {"name": "Surface", "value": f"{surface.capitalize()} wind; {wind:.0f} kt"},
        ]
    )
    return result
