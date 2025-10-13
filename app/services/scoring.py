from typing import Tuple
CARDINALS = {"N":0,"NE":45,"E":90,"SE":135,"S":180,"SW":225,"W":270,"NW":315}
def ang_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)
def bucket(score: float) -> str:
    return "bad" if score < 40 else "ok" if score < 60 else "good" if score < 80 else "epic"
def score_spot(spot, wind_dir: float, wind_kts: float, gust_kts: float, wave_height_m=None) -> Tuple[float, str, str]:
    preferred = [CARDINALS.get(c, 0) for c in spot.fetch_hints]
    best_alignment = max(0, 100 - (min(ang_diff(wind_dir, d) for d in preferred) / 90) * 100) if preferred else 0
    if wind_kts < spot.min_wind_kts:
        speed = max(0, (wind_kts / max(1, spot.min_wind_kts)) * 70)
    elif wind_kts <= spot.max_wind_kts:
        speed = 100
    else:
        over = min(15, wind_kts - spot.max_wind_kts)
        speed = max(40, 100 - (over / 15) * 60)
    onshore_bias = ang_diff(wind_dir, spot.shoreline_orientation)
    onshore_score = max(0, 100 - (onshore_bias / 90) * 100) * 0.7
    cross_score = max(0, (1 - abs(45 - onshore_bias)/45) * 100) * 0.3
    wind_quality = max(onshore_score, cross_score)
    gust_spread = max(0, gust_kts - wind_kts)
    stability = max(0, 100 - min(100, gust_spread * 6))
    wave_bonus = 0
    if wave_height_m is not None:
        wave_bonus = max(0, min(20, (wave_height_m - 0.5) * 25))
    final = 0.40*best_alignment + 0.35*speed + 0.15*wind_quality + 0.10*stability + wave_bonus
    final = max(0, min(100, final))
    b = "bad" if final < 40 else "ok" if final < 60 else "good" if final < 80 else "epic"
    reason = f"{int(round(wind_kts))} kts @ {int(round(wind_dir))}°, gust {int(round(gust_kts))} — align {int(best_alignment)}/100"
    return final, b, reason
