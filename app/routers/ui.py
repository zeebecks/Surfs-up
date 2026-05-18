from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import hmac
import os
from sqlalchemy import text
from zoneinfo import ZoneInfo
from ..services.spot_repo import get_all_spots
from ..services.forecast import get_forecast_for
from ..services.scoring import score_spot
from ..services.util import get_session
import secrets
import httpx
from fastapi.responses import StreamingResponse
from urllib.parse import urlparse

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "America/Chicago"))


def _today_utc_bounds() -> tuple[str, str]:
    now_local = datetime.now(APP_TIMEZONE)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    end_utc = end_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return start_utc, end_utc


def _purge_stale_checkins(db) -> None:
    start_utc, _ = _today_utc_bounds()
    db.execute(text("""
        DELETE FROM checkins
        WHERE created_at < :start_utc
    """), {"start_utc": start_utc})


def _today_checkin_counts(db) -> dict[str, int]:
    start_utc, end_utc = _today_utc_bounds()
    rows = db.execute(text("""
        SELECT spot_id, COUNT(*) AS total
        FROM checkins
        WHERE created_at >= :start_utc
          AND created_at < :end_utc
        GROUP BY spot_id
    """), {"start_utc": start_utc, "end_utc": end_utc})
    return {row.spot_id: row.total for row in rows}

@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    try:
        h = int(request.query_params.get("h", "0"))
    except Exception:
        h = 0
    if h not in (0,3,6):
        h = 0
    notes_error_spot = request.query_params.get("notes_error_spot", "")
    at = datetime.now(timezone.utc) + timedelta(hours=h)

    with get_session() as db:
        _purge_stale_checkins(db)
        checkin_counts = _today_checkin_counts(db)
        db.commit()

    spots = get_all_spots()
    items = []; items_js = []
    for s in spots:
        fc = get_forecast_for(s.lat, s.lng, at=at)
        score, bucket, reason = score_spot(s, fc.wind_dir_deg, fc.wind_kts, fc.gust_kts, fc.wave_height_m)
        reason = f"{reason}"
        checkin_count = checkin_counts.get(s.id, 0)
        items.append({ "spot": s, "score": score, "bucket": bucket, "reason": reason, "wind_dir_deg": fc.wind_dir_deg, "checkin_count": checkin_count })
        items_js.append({ "spot": asdict(s), "score": score, "bucket": bucket, "reason": reason, "wind_dir_deg": fc.wind_dir_deg, "checkin_count": checkin_count })
    items.sort(key=lambda x: x["score"], reverse=True)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "items": items,
        "items_js": items_js,
        "h": h,
        "notes_error_spot": notes_error_spot,
    })

@router.post("/checkins")
def create_checkin(user_id: str = Form(...), spot_id: str = Form(...),
                   arrive_start: str = Form(...), arrive_end: str = Form(...),
                   note: str = Form(""), visibility: str = Form("friends")):
    delete_token = secrets.token_urlsafe(16)
    with get_session() as db:
        _purge_stale_checkins(db)
        res = db.execute(text("""
            INSERT INTO checkins (user_id, spot_id, arrive_start, arrive_end, note, visibility, delete_token)
            VALUES (:user_id, :spot_id, :arrive_start, :arrive_end, :note, :visibility, :delete_token)
        """), {
            "user_id": user_id, "spot_id": spot_id,
            "arrive_start": arrive_start, "arrive_end": arrive_end,
            "note": note, "visibility": visibility,
            "delete_token": delete_token
        })
        checkin_id = res.lastrowid
        db.commit()
    return RedirectResponse(
        url=f"/?spot_id={spot_id}&checkin_id={checkin_id}&token={delete_token}",
        status_code=303
    )


@router.get("/checkins/delete")
def delete_checkin(id: int, token: str):
    with get_session() as db:
        db.execute(text("""
            DELETE FROM checkins
            WHERE id = :id AND delete_token = :token
        """), {"id": id, "token": token})
        db.commit()
    return RedirectResponse(url="/?deleted=1", status_code=303)



@router.post("/spot-notes")
def update_spot_notes(spot_id: str = Form(...),
                      notes: str = Form(""),
                      editor_name: str = Form(...),
                      password: str = Form(...)):
    expected_password = os.getenv("NOTES_ADMIN_PASSWORD", "")
    if not expected_password or not hmac.compare_digest(password, expected_password):
        return RedirectResponse(url=f"/?notes_error_spot={spot_id}", status_code=303)
    edited_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    with get_session() as db:
        db.execute(text("""
            UPDATE spots
            SET notes = :notes,
                notes_edited_by = :edited_by,
                notes_edited_at = :edited_at
            WHERE id = :spot_id
        """), {
            "spot_id": spot_id,
            "notes": notes,
            "edited_by": editor_name,
            "edited_at": edited_at
        })
        db.commit()
    return RedirectResponse(url="/", status_code=303)


@router.get("/crew", response_class=HTMLResponse)
def crew(request: Request):
    with get_session() as db:
        start_utc, end_utc = _today_utc_bounds()
        _purge_stale_checkins(db)
        rows = db.execute(text("""
            SELECT c.*, s.name as spot_name FROM checkins c
            JOIN spots s ON s.id = c.spot_id
            WHERE c.created_at >= :start_utc
              AND c.created_at < :end_utc
            ORDER BY c.arrive_start ASC
        """), {"start_utc": start_utc, "end_utc": end_utc})
        checkins = [dict(r) for r in rows.mappings().all()]
        db.commit()
    return templates.TemplateResponse("crew.html", {"request": request, "checkins": checkins})


@router.get("/camera/two-rivers")
def two_rivers_camera():
    url = "http://harborcam.two-rivers.org/mjpg/video.mjpg?camera=1&resolution=1920x1080"

    def iter_stream():
        with httpx.stream("GET", url, timeout=None) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes():
                yield chunk

    with httpx.stream("GET", url, timeout=None) as r:
        r.raise_for_status()
        content_type = r.headers.get("content-type", "multipart/x-mixed-replace")
    return StreamingResponse(iter_stream(), media_type=content_type)


@router.get("/camera/port-washington")
def port_washington_camera():
    url = "http://24.106.61.2:8081/mjpg/video.mjpg?audiocodec=aac&audiosamplerate=16000&audiobitrate=32000&camera=1&videoframeskipmode=empty&videozprofile=classic&resolution=1920x1080&audiodeviceid=0&audioinputid=0&timestamp=7&cachebust=5"

    def iter_stream():
        with httpx.stream("GET", url, timeout=None) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes():
                yield chunk

    with httpx.stream("GET", url, timeout=None) as r:
        r.raise_for_status()
        content_type = r.headers.get("content-type", "multipart/x-mixed-replace")
    return StreamingResponse(iter_stream(), media_type=content_type)


@router.get("/camera/kewaunee")
def kewaunee_camera():
    spots = get_all_spots()
    spot = next((s for s in spots if s.id == "kewaunee"), None)
    if not spot or not spot.camera_url:
        return RedirectResponse(url="/", status_code=307)

    parsed = urlparse(spot.camera_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    url = f"{base_url}/mjpg/video.mjpg"

    def iter_stream():
        with httpx.stream("GET", url, timeout=None) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes():
                yield chunk

    with httpx.stream("GET", url, timeout=None) as r:
        r.raise_for_status()
        content_type = r.headers.get("content-type", "multipart/x-mixed-replace")
    return StreamingResponse(iter_stream(), media_type=content_type)
