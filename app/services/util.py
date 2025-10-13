from contextlib import contextmanager
from ..database import SessionLocal
@contextmanager
def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
