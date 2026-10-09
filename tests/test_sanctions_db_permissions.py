"""
Tests for watchlist_entries database schema, check constraints, and role permissions.

Verifies:
- Least privilege for app_role: SELECT only (no INSERT, UPDATE, DELETE)
- Least privilege for loader_role: SELECT, INSERT only (no UPDATE, DELETE)
- Check constraints: name_type, listed_name non-blank, is_synthetic=true
- Unique natural key constraint
"""

import pytest
from sqlalchemy import Engine, text

INSERT_ENTRY_SQL = (
    "INSERT INTO watchlist_entries "
    "(entry_id, watchlist_name, watchlist_version, subject_key, name_type, "
    " listed_name, is_synthetic, source) "
    "VALUES (gen_random_uuid(), :w_name, :w_ver, :s_key, :n_type, "
    "        :l_name, :is_synth, :source)"
)


@pytest.fixture(autouse=True)
def clean_watchlist(superuser_engine: Engine) -> None:
    """Clean table before and after test."""
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM watchlist_entries"))
    yield
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM watchlist_entries"))


def test_app_role_cannot_insert_or_modify_watchlist(
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:
    """Verify application DB role is SELECT-only on watchlist_entries."""
    # Seed 1 row as superuser
    with superuser_engine.begin() as conn:
        conn.execute(
            text(INSERT_ENTRY_SQL),
            {
                "w_name": "test_list",
                "w_ver": "v1",
                "s_key": "SUBJ-1",
                "n_type": "primary",
                "l_name": "Test Person",
                "is_synth": True,
                "source": "test",
            },
        )

    with app_role_engine.connect() as conn:
        # SELECT succeeds
        rows = conn.execute(text("SELECT * FROM watchlist_entries")).fetchall()
        assert len(rows) == 1

        # INSERT fails
        with pytest.raises(Exception) as excinfo:
            conn.execute(
                text(INSERT_ENTRY_SQL),
                {
                    "w_name": "test_list",
                    "w_ver": "v1",
                    "s_key": "SUBJ-2",
                    "n_type": "primary",
                    "l_name": "Hacker",
                    "is_synth": True,
                    "source": "test",
                },
            )
            conn.commit()
        assert "permission denied" in str(excinfo.value).lower()
        conn.rollback()

        # UPDATE fails
        with pytest.raises(Exception) as excinfo:
            conn.execute(
                text("UPDATE watchlist_entries SET listed_name = 'Hacked'")
            )
            conn.commit()
        assert "permission denied" in str(excinfo.value).lower()
        conn.rollback()

        # DELETE fails
        with pytest.raises(Exception) as excinfo:
            conn.execute(text("DELETE FROM watchlist_entries"))
            conn.commit()
        assert "permission denied" in str(excinfo.value).lower()
        conn.rollback()


def test_loader_role_permissions_and_restrictions(
    loader_role_engine: Engine,
) -> None:
    """Verify loader role has SELECT, INSERT but cannot UPDATE or DELETE."""
    with loader_role_engine.connect() as conn:
        # INSERT succeeds
        conn.execute(
            text(INSERT_ENTRY_SQL),
            {
                "w_name": "test_list",
                "w_ver": "v1",
                "s_key": "SUBJ-1",
                "n_type": "primary",
                "l_name": "Valid Person",
                "is_synth": True,
                "source": "test",
            },
        )
        conn.commit()

        # SELECT succeeds
        rows = conn.execute(text("SELECT * FROM watchlist_entries")).fetchall()
        assert len(rows) == 1

        # UPDATE fails (immutable versions)
        with pytest.raises(Exception) as excinfo:
            conn.execute(
                text("UPDATE watchlist_entries SET listed_name = 'Mutated'")
            )
            conn.commit()
        assert "permission denied" in str(excinfo.value).lower()
        conn.rollback()

        # DELETE fails (immutable versions)
        with pytest.raises(Exception) as excinfo:
            conn.execute(text("DELETE FROM watchlist_entries"))
            conn.commit()
        assert "permission denied" in str(excinfo.value).lower()
        conn.rollback()


def test_check_constraints_negative(superuser_engine: Engine) -> None:
    """Verify check constraints for name_type, non-blank, and is_synthetic."""
    # Invalid name_type
    with pytest.raises(Exception) as excinfo:
        with superuser_engine.begin() as conn:
            conn.execute(
                text(INSERT_ENTRY_SQL),
                {
                    "w_name": "test",
                    "w_ver": "v1",
                    "s_key": "S1",
                    "n_type": "invalid_type",
                    "l_name": "Name",
                    "is_synth": True,
                    "source": "src",
                },
            )
    err = str(excinfo.value).lower()
    assert "ck_watchlist_entries_name_type" in err or "check constraint" in err

    # Blank listed_name
    with pytest.raises(Exception) as excinfo:
        with superuser_engine.begin() as conn:
            conn.execute(
                text(INSERT_ENTRY_SQL),
                {
                    "w_name": "test",
                    "w_ver": "v1",
                    "s_key": "S1",
                    "n_type": "primary",
                    "l_name": "   ",
                    "is_synth": True,
                    "source": "src",
                },
            )
    err = str(excinfo.value).lower()
    assert (
        "ck_watchlist_entries_listed_name_non_blank" in err
        or "check constraint" in err
    )

    # Non-synthetic (is_synthetic=false)
    with pytest.raises(Exception) as excinfo:
        with superuser_engine.begin() as conn:
            conn.execute(
                text(INSERT_ENTRY_SQL),
                {
                    "w_name": "test",
                    "w_ver": "v1",
                    "s_key": "S1",
                    "n_type": "primary",
                    "l_name": "Name",
                    "is_synth": False,
                    "source": "src",
                },
            )
    err = str(excinfo.value).lower()
    assert "ck_watchlist_entries_is_synthetic" in err or "check constraint" in err


def test_natural_key_unique_constraint(superuser_engine: Engine) -> None:
    """Verify duplicate natural key raises unique constraint violation."""
    with superuser_engine.begin() as conn:
        conn.execute(
            text(INSERT_ENTRY_SQL),
            {
                "w_name": "test_list",
                "w_ver": "v1",
                "s_key": "S1",
                "n_type": "primary",
                "l_name": "Duplicate Name",
                "is_synth": True,
                "source": "src",
            },
        )
        with pytest.raises(Exception) as excinfo:
            conn.execute(
                text(INSERT_ENTRY_SQL),
                {
                    "w_name": "test_list",
                    "w_ver": "v1",
                    "s_key": "S1",
                    "n_type": "primary",
                    "l_name": "Duplicate Name",
                    "is_synth": True,
                    "source": "src",
                },
            )
        err = str(excinfo.value).lower()
        assert (
            "uq_watchlist_entries_natural_key" in err
            or "unique constraint" in err
        )
