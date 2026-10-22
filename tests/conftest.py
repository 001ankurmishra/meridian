import os
from typing import Generator

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine

from alembic import command
from meridian.testing.guard import (
    ALEMBIC_GUARD_ATTRIBUTE,
    verify_teardown_safety,
    verify_test_database_safety,
)
from meridian.testing.guard import (
    pytest_addoption as guard_addoption,
)
from meridian.testing.guard import (
    pytest_collection_modifyitems as guard_collection_modifyitems,
)
from meridian.testing.guard import (
    pytest_configure as guard_configure,
)

# Export standard pytest hooks for offline unit test mode
pytest_configure = guard_configure
pytest_addoption = guard_addoption
pytest_collection_modifyitems = guard_collection_modifyitems


@pytest.fixture(scope="session", autouse=True)
def run_migrations(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """
    Guarded Alembic migration fixture.
    1. Bypassed in offline unit test mode (--offline-unit-tests).
    2. In normal mode, enforces fail-closed test database validation before upgrade.
    3. Supplies validated URL and in-memory signal to Alembic.
    4. Re-validates TargetIdentity in teardown before permitting downgrade.
    """
    if request.config.getoption("--offline-unit-tests", default=False):
        yield
        return

    # 1. Enforce pre-migration safety validation
    target_identity, escaped_url = verify_test_database_safety()

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.attributes[ALEMBIC_GUARD_ATTRIBUTE] = target_identity.validated_url
    alembic_cfg.set_main_option("sqlalchemy.url", escaped_url)

    command.upgrade(alembic_cfg, "head")

    try:
        yield
    finally:
        # 2. Re-verify target identity before teardown downgrade
        escaped_teardown_url = verify_teardown_safety(target_identity)
        alembic_cfg.attributes[ALEMBIC_GUARD_ATTRIBUTE] = target_identity.validated_url
        alembic_cfg.set_main_option("sqlalchemy.url", escaped_teardown_url)

        command.downgrade(alembic_cfg, "base")
        command.upgrade(alembic_cfg, "head")


@pytest.fixture
def superuser_engine() -> Generator[Engine, None, None]:
    """Engine using the migrator/superuser role (DATABASE_URL)."""
    db_url = os.environ["DATABASE_URL"]
    engine = create_engine(db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def app_role_engine() -> Generator[Engine, None, None]:
    """Engine using the least-privilege application role (APP_DATABASE_URL)."""
    app_db_url = os.environ["APP_DATABASE_URL"]
    engine = create_engine(app_db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def loader_role_engine() -> Generator[Engine, None, None]:
    """Engine using the least-privilege loader role (LOADER_DATABASE_URL)."""
    loader_db_url = os.environ["LOADER_DATABASE_URL"]
    engine = create_engine(loader_db_url)
    yield engine
    engine.dispose()
