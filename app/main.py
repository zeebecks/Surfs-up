from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .database import init_db
from .services.spot_repo import seed_spots_if_empty
from .routers import ui

app = FastAPI(title="Lake Surf MVP")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.on_event("startup")
def startup():
    init_db()
    seed_spots_if_empty()

app.include_router(ui.router)
