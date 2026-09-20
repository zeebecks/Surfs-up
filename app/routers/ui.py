import hmac
import os
import secrets
from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from starlette.background import BackgroundTask

from ..services.catalog import CAMERAS, GUIDES, STREAMS, WINDFINDER
from ..services.scoring import rate
from ..services.spot_repo import get_all_spots
from ..services.util import get_session
from ..services.weather import parse_time, stamp, utcnow, weather

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "America/Chicago"))


def cardinal(degrees):
    return (
        "—"
        if degrees is None
        else "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()[
            int((degrees + 11.25) // 22.5) % 16
        ]
    )


def age(value):
    if not value:
        return "Not available"
    minutes = max(0, int((utcnow() - parse_time(value)).total_seconds() / 60))
    return (
        "Just updated"
        if minutes < 1
        else f"{minutes}m ago"
        if minutes < 60
        else f"{minutes // 60}h {minutes % 60}m ago"
        if minutes < 1440
        else f"{minutes // 1440}d ago"
    )


def localtime(value, fmt="%a %-I:%M %p %Z"):
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Reports saved by the original app used local time without an offset.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=APP_TIMEZONE)
        return parsed.astimezone(APP_TIMEZONE).strftime(fmt)
    except (ValueError, TypeError):
        return "Unknown time"


templates.env.filters.update(cardinal=cardinal, age=age, localtime=localtime)


def _today_utc_bounds():
    start = datetime.now(APP_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    return tuple(
        t.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for t in (start, start + timedelta(days=1))
    )


def _purge_stale_checkins(db):
    start, _ = _today_utc_bounds()
    db.execute(text("DELETE FROM checkins WHERE created_at < :start"), {"start": start})


def counts():
    start, end = _today_utc_bounds()
    with get_session() as db:
        return dict(
            db.execute(
                text(
                    "SELECT spot_id,COUNT(*) FROM checkins WHERE created_at >= :start AND created_at < :end GROUP BY spot_id"
                ),
                {"start": start, "end": end},
            ).all()
        )


def get_spot(spot_id):
    spot = next((s for s in get_all_spots() if s.id == spot_id), None)
    if not spot:
        raise HTTPException(404, "Spot not found")
    return spot


def hours(request):
    try:
        result = int(request.query_params.get("h", "0"))
    except ValueError:
        return 0
    return result if result in {0, 3, 6, 12, 24} else 0


def present(spot, at, checkins=0):
    fc = weather.forecast(spot.id, at)
    rating = rate(spot, fc)
    return {
        "spot": spot,
        "forecast": fc,
        "rating": rating,
        "camera": CAMERAS.get(spot.id),
        "guide": GUIDES.get(spot.id, ""),
        "checkins": checkins,
        "name": spot.name.replace(" — ", " / "),
        "windfinder": WINDFINDER.get(spot.id),
    }


def render(request, template, **context):
    station_data = context.get("stations", [])
    if template != "buoys.html":
        station_data = [{**station, "history": []} for station in station_data]
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "demo": weather.demo,
            "weather_ready": weather.ready,
            "refreshing": weather.refreshing,
            "now": stamp(utcnow()),
            "active": "spots",
            "station_data": station_data,
            **context,
        },
    )


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    h = hours(request)
    at = utcnow().replace(minute=0, second=0, microsecond=0) + timedelta(hours=h)
    checkins = counts()
    items = [
        present(s, at, checkins.get(s.id, 0))
        for s in sorted(get_all_spots(), key=lambda s: s.lat, reverse=True)
    ]
    return render(
        request,
        "index.html",
        items=items,
        stations=weather.stations(),
        h=h,
        at=stamp(at),
        station_count=sum(s["status"] in {"fresh", "demo"} for s in weather.stations()),
    )


@router.get("/spots/{spot_id}", response_class=HTMLResponse)
def detail(request: Request, spot_id: str):
    spot = get_spot(spot_id)
    h = hours(request)
    start = utcnow().replace(minute=0, second=0, microsecond=0)
    at = start + timedelta(hours=h)
    hourly = [
        {
            "time": stamp(start + timedelta(hours=i)),
            **weather.forecast(spot_id, start + timedelta(hours=i)),
        }
        for i in range(48)
    ]
    associated = {"45002", "45007"}
    if spot_id.startswith("sheboygan"):
        associated.add("SGNW3")
    elif spot_id == "port-washington":
        associated.add("PWAW3")
    return render(
        request,
        "spot.html",
        item=present(spot, at, counts().get(spot_id, 0)),
        hourly=hourly,
        stations=[s for s in weather.stations() if s["id"] in associated],
        h=h,
        at=stamp(at),
        notes_enabled=bool(os.getenv("NOTES_ADMIN_PASSWORD")),
        notes_error=request.query_params.get("notes_error") == "1",
    )


@router.get("/buoys", response_class=HTMLResponse)
def buoys(request: Request):
    return render(request, "buoys.html", active="buoys", stations=weather.stations())


@router.get("/about", response_class=HTMLResponse)
def about(request: Request):
    return render(request, "about.html", active="about")


@router.get("/api/status")
def status():
    records = [weather.get(f"wind:{s.id}") for s in get_all_spots()]
    records += [weather.get(f"waves:{s.id}") for s in get_all_spots()]
    records += [weather.get(f"buoy:{s['id']}") for s in weather.stations()]
    return {
        "ready": weather.ready,
        "refreshing": weather.refreshing,
        "revision": max(
            (r.get("attempted_at", r.get("fetched_at", "")) for r in records if r), default=""
        ),
        "demo": weather.demo,
    }


@router.post("/checkins")
def create_checkin(
    user_id: str = Form(..., min_length=1, max_length=60),
    spot_id: str = Form(...),
    arrive_start: str = Form(...),
    arrive_end: str = Form(...),
    note: str = Form("", max_length=280),
):
    get_spot(spot_id)
    try:
        start, end = time.fromisoformat(arrive_start), time.fromisoformat(arrive_end)
        if start.tzinfo or end.tzinfo or end <= start or not user_id.strip():
            raise ValueError
    except ValueError:
        raise HTTPException(
            422, "Enter a name and a same-day time window with departure after arrival."
        )
    token = secrets.token_urlsafe(24)
    with get_session() as db:
        _purge_stale_checkins(db)
        result = db.execute(
            text(
                "INSERT INTO checkins (user_id,spot_id,arrive_start,arrive_end,note,visibility,delete_token) VALUES (:user,:spot,:start,:end,:note,'public',:token)"
            ),
            {
                "user": user_id.strip(),
                "spot": spot_id,
                "start": start.strftime("%H:%M"),
                "end": end.strftime("%H:%M"),
                "note": note,
                "token": token,
            },
        )
        ident = result.lastrowid
        db.commit()
    # Fragment is processed locally and never sent in requests or Referer headers.
    return RedirectResponse(
        "/crew#" + urlencode({"checkin_id": ident, "token": token}), status_code=303
    )


@router.post("/checkins/delete")
def delete_checkin(id: int = Form(...), token: str = Form(..., max_length=200)):
    with get_session() as db:
        db.execute(
            text("DELETE FROM checkins WHERE id=:id AND delete_token=:token"),
            {"id": id, "token": token},
        )
        db.commit()
    return RedirectResponse("/crew", status_code=303)


@router.post("/spot-notes")
def update_spot_notes(
    spot_id: str = Form(...),
    notes: str = Form("", max_length=2000),
    editor_name: str = Form(..., min_length=1, max_length=60),
    password: str = Form(..., max_length=200),
):
    get_spot(spot_id)
    expected = os.getenv("NOTES_ADMIN_PASSWORD", "")
    if not expected or not hmac.compare_digest(password.encode(), expected.encode()):
        return RedirectResponse(f"/spots/{spot_id}?notes_error=1#field-notes", status_code=303)
    if not editor_name.strip():
        raise HTTPException(422, "An editor name is required")
    with get_session() as db:
        db.execute(
            text(
                "UPDATE spots SET notes=:notes,notes_edited_by=:editor,notes_edited_at=:at WHERE id=:id"
            ),
            {"notes": notes, "editor": editor_name.strip(), "at": stamp(utcnow()), "id": spot_id},
        )
        db.commit()
    return RedirectResponse(f"/spots/{spot_id}#field-notes", status_code=303)


@router.get("/crew", response_class=HTMLResponse)
def crew(request: Request):
    start, end = _today_utc_bounds()
    with get_session() as db:
        rows = db.execute(
            text(
                "SELECT c.id,c.user_id,c.spot_id,c.arrive_start,c.arrive_end,c.note,s.name as spot_name FROM checkins c JOIN spots s ON s.id=c.spot_id WHERE c.created_at >= :start AND c.created_at < :end ORDER BY c.arrive_start"
            ),
            {"start": start, "end": end},
        )
        checkins = [dict(r) for r in rows.mappings()]
    return render(request, "crew.html", active="crew", checkins=checkins, spots=get_all_spots())


@router.get("/camera/{camera_id}")
async def camera(camera_id: str):
    if camera_id not in STREAMS:
        raise HTTPException(404, "Camera not found")
    client = httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5), follow_redirects=True)
    try:
        response = await client.send(client.build_request("GET", STREAMS[camera_id]), stream=True)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if not content_type.startswith(("multipart/", "image/")):
            raise ValueError("Camera returned an unsupported format")
    except (httpx.HTTPError, ValueError):
        await client.aclose()
        raise HTTPException(503, "Camera unavailable. Try the original camera page.")

    async def close():
        await response.aclose()
        await client.aclose()

    async def frames():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        except httpx.HTTPError:
            return
        finally:
            await close()

    return StreamingResponse(
        frames(),
        headers={"Content-Type": content_type, "Cache-Control": "no-store"},
        background=BackgroundTask(close),
    )
