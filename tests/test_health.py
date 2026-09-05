from fastapi.testclient import TestClient
from sqlalchemy import text

from meridian.db.session import engine, get_db
from meridian.main import app

client = TestClient(app)


def test_health_check_ok() -> None:
    # This test expects the DB to be up and running via docker-compose
    # or similar setup in CI
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_health_check_db_unavailable() -> None:
    from collections.abc import Generator

    from sqlalchemy.orm import Session

    def override_get_db() -> Generator[Session, None, None]:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        # Point to a definitely unreachable port
        bad_engine = create_engine(
            "postgresql+psycopg://user:pass@localhost:54321/bad_db",
            connect_args={"connect_timeout": 1},
        )
        TestingSessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=bad_engine
        )
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json() == {"status": "degraded", "database": "unavailable"}
    finally:
        # Clear override
        app.dependency_overrides.clear()


def test_pgvector_extension_exists() -> None:
    # Verify that the vector extension is available in the database
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.commit()

        result = conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector';")
        )
        version = result.scalar()
        assert version is not None, "pgvector extension is not installed or available."
