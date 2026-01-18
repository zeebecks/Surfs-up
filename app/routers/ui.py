from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from ..services.spot_repo import get_all_spots
from ..services.forecast import get_forecast_for
from ..services.scoring import score_spot
from ..services.util import get_session
import secrets

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    try:
        h = int(request.query_params.get("h", "0"))
    except Exception:
        h = 0
    if h not in (0,3,6):
        h = 0
    at = datetime.now(timezone.utc) + timedelta(hours=h)

    spots = get_all_spots()
    items = []; items_js = []
    for s in spots:
        fc = get_forecast_for(s.lat, s.lng, at=at)
        score, bucket, reason = score_spot(s, fc.wind_dir_deg, fc.wind_kts, fc.gust_kts, fc.wave_height_m)
        reason = f"{reason} · {fc.source.upper()}"
        items.append({ "spot": s, "score": score, "bucket": bucket, "reason": reason })
        items_js.append({ "spot": asdict(s), "score": score, "bucket": bucket, "reason": reason })
    items.sort(key=lambda x: x["score"], reverse=True)
    return templates.TemplateResponse("index.html", {"request": request, "items": items, "items_js": items_js, "h": h})

@router.post("/checkins")
def create_checkin(user_id: str = Form(...), spot_id: str = Form(...),
                   arrive_start: str = Form(...), arrive_end: str = Form(...),
                   note: str = Form(""), visibility: str = Form("friends")):
    delete_token = secrets.token_urlsafe(16)
    with get_session() as db:
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
                      editor_name: str = Form(...)):
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
        rows = db.execute(text("""
            SELECT c.*, s.name as spot_name FROM checkins c
            JOIN spots s ON s.id = c.spot_id
            ORDER BY c.arrive_start ASC
        """))
        checkins = [dict(r) for r in rows.mappings().all()]
    return templates.TemplateResponse("crew.html", {"request": request, "checkins": checkins})
