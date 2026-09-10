import os
from typing import Generator

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine

from alembic import command


@pytest.fixture(scope="session", autouse=True)
def run_migrations() -> Generator[None, None, None]:
    """Run Alembic migrations before the test session and tear down after."""
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    yield
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")


@pytest.fixture
def superuser_engine() -> Generator[Engine, None, None]:
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://meridian_user:meridian_pass@localhost:5432/meridian_db",
    )
    engine = create_engine(db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def app_role_engine() -> Generator[Engine, None, None]:
    app_db_url = os.environ.get(
        "APP_DATABASE_URL",
        "postgresql+psycopg://meridian_app:meridian_app_pass@localhost:5432/meridian_db",
    )
    engine = create_engine(app_db_url)
    yield engine
    engine.dispose()

@pytest.fixture
def loader_role_engine() -> Generator[Engine, None, None]:
    loader_db_url = os.environ.get(
        "LOADER_DATABASE_URL",
        "postgresql+psycopg://meridian_loader:meridian_loader_pass@localhost:5432/meridian_db",
    )
    engine = create_engine(loader_db_url)
    yield engine
    engine.dispose()
