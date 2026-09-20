import asyncio
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .database import init_db
from .routers import ui
from .services.spot_repo import get_all_spots, seed_spots_if_empty
from .services.weather import refresh_loop, weather


@asynccontextmanager
async def lifespan(app):
    init_db()
    seed_spots_if_empty()
    spots = get_all_spots()
    task = None
    if os.getenv("SURF_DEMO", "0") == "1":
        weather.load_demo(spots)
    else:
        weather.load()
        if os.getenv("WEATHER_REFRESH", "1") != "0":
            task = asyncio.create_task(refresh_loop(spots))
    yield
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Lake Surf", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(ui.router)
