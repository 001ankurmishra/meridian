from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from meridian.case_management.alert_intake import get_app_engine


@lru_cache()
def get_runtime_engine() -> Engine:
    return get_app_engine()


def get_db() -> Generator[Session, None, None]:
    with Session(get_runtime_engine()) as db:
        yield db
