import csv, json, os
from sqlalchemy import text
from .util import get_session
from ..models import Spot
SPOTS_CSV = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "spots.csv")
def seed_spots_if_empty():
    with get_session() as db:
        count = db.execute(text("SELECT COUNT(1) FROM spots")).scalar()
        if count and count > 0:
            return
        with open(SPOTS_CSV, newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                db.execute(text("""
                    INSERT OR REPLACE INTO spots
                    (id, name, lat, lng, shoreline_orientation, fetch_hints, min_wind_kts, max_wind_kts, notes, camera_url, quality_offset)
                    VALUES (:id, :name, :lat, :lng, :so, :fh, :minw, :maxw, :notes, :camera_url, :quality_offset)
                """), {
                    "id": row["id"],
                    "name": row["name"],
                    "lat": float(row["lat"]),
                    "lng": float(row["lng"]),
                    "so": int(row["shoreline_orientation"]),
                    "fh": row["fetch_hints"],
                    "minw": int(row["min_wind_kts"]),
                    "maxw": int(row["max_wind_kts"]),
                    "notes": row["notes"],
                    "camera_url": row.get("camera_url", ""),
                    "quality_offset": float(row.get("quality_offset") or 0)
                })
        db.commit()
def get_all_spots():
    with get_session() as db:
        rs = db.execute(text("SELECT * FROM spots")).mappings().all()
        spots = []
        for r in rs:
            spots.append(Spot(
                id=r["id"], name=r["name"], lat=r["lat"], lng=r["lng"],
                shoreline_orientation=r["shoreline_orientation"],
                fetch_hints=json.loads(r["fetch_hints"]),
                min_wind_kts=r["min_wind_kts"], max_wind_kts=r["max_wind_kts"],
                notes=r["notes"] or "",
                camera_url=r["camera_url"] or "",
                quality_offset=r["quality_offset"] or 0
            ))
        return spots
