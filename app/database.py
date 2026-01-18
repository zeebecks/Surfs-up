from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./surf.db")
engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    with engine.begin() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS spots (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          lat REAL NOT NULL,
          lng REAL NOT NULL,
          shoreline_orientation INTEGER NOT NULL,
          fetch_hints TEXT NOT NULL,
          min_wind_kts INTEGER NOT NULL,
          max_wind_kts INTEGER NOT NULL,
          notes TEXT,
          notes_edited_by TEXT,
          notes_edited_at TEXT
          camera_url TEXT,
          quality_offset REAL
        );"""))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS checkins (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id TEXT,
          spot_id TEXT,
          arrive_start TEXT,
          arrive_end TEXT,
          note TEXT,
          visibility TEXT DEFAULT 'friends',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );"""))
