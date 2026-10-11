import csv
import json
import os

from sqlalchemy import text

from ..models import Spot
from .util import get_session

SPOTS_CSV = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "spots.csv")
DEFAULT_SPOT_ORDER = (
    "north-pier-two-rivers",
    "sheboygan-elbow",
    "sheboygan-blue-harbor",
    "port-washington",
    "manitowoc-south-pier",
    "kewaunee",
)


def seed_spots_if_empty():
    with get_session() as db:
        with open(SPOTS_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                db.execute(
                    text("""
                    INSERT INTO spots
                    (id, name, lat, lng, shoreline_orientation, fetch_hints, min_wind_kts, max_wind_kts, notes, camera_url, quality_offset)
                    VALUES (:id, :name, :lat, :lng, :so, :fh, :minw, :maxw, :notes, :camera_url, :quality_offset)
                    ON CONFLICT(id) DO NOTHING
                """),
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "lat": float(row["lat"]),
                        "lng": float(row["lng"]),
                        "so": int(row["shoreline_orientation"]),
                        "fh": row["fetch_hints"],
                        "minw": int(row["min_wind_kts"]),
                        "maxw": int(row["max_wind_kts"]),
                        "notes": row["notes"],
                        "notes_edited_by": "",
                        "notes_edited_at": "",
                        "camera_url": row.get("camera_url", ""),
                        "quality_offset": float(row.get("quality_offset") or 0),
                    },
                )
        # Apply the display-name correction to existing databases without
        # changing the stable spot ID, saved favorites, or edited notes.
        db.execute(
            text("UPDATE spots SET name=:name WHERE id=:id AND name=:old_name"),
            {
                "id": "manitowoc-south-pier",
                "name": "Manitowoc - Yacht Club",
                "old_name": "Manitowoc — South Pier",
            },
        )
        db.commit()


def get_all_spots():
    with get_session() as db:
        rs = db.execute(text("SELECT * FROM spots")).mappings().all()
        spots = []
        for r in rs:
            spots.append(
                Spot(
                    id=r["id"],
                    name=r["name"],
                    lat=r["lat"],
                    lng=r["lng"],
                    shoreline_orientation=r["shoreline_orientation"],
                    fetch_hints=json.loads(r["fetch_hints"]),
                    min_wind_kts=r["min_wind_kts"],
                    max_wind_kts=r["max_wind_kts"],
                    notes=r["notes"] or "",
                    notes_edited_by=r["notes_edited_by"] or "",
                    notes_edited_at=r["notes_edited_at"] or "",
                    camera_url=r["camera_url"] or "",
                    quality_offset=r["quality_offset"] or 0,
                )
            )
        order = {spot_id: index for index, spot_id in enumerate(DEFAULT_SPOT_ORDER)}
        return sorted(spots, key=lambda spot: (order.get(spot.id, len(order)), spot.name))
