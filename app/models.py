from dataclasses import dataclass
from typing import List
@dataclass
class Spot:
    id: str
    name: str
    lat: float
    lng: float
    shoreline_orientation: int
    fetch_hints: List[str]
    min_wind_kts: int
    max_wind_kts: int
    notes: str = ""
    camera_url: str = ""
    quality_offset: float = 0.0
