import uuid
from typing import Optional

from sqlalchemy import Connection, text


def clean_investigation_run_dependencies(
    conn: Connection, investigation_run_id: Optional[uuid.UUID | str] = None
) -> None:
    """
    Centralized helper for test database cleanup.
    Explicitly deletes dependent tables in the correct FK order before deleting investigation_runs.
    """
    if investigation_run_id:
        params = {"rid": str(investigation_run_id)}
        conn.execute(
            text("DELETE FROM recommendations WHERE investigation_run_id = :rid"),
            params,
        )
        conn.execute(
            text("DELETE FROM findings WHERE investigation_run_id = :rid"), params
        )
        conn.execute(
            text("DELETE FROM evidence WHERE investigation_run_id = :rid"), params
        )
        conn.execute(
            text("DELETE FROM risk_signals WHERE investigation_run_id = :rid"), params
        )
        conn.execute(
            text("DELETE FROM agent_runs WHERE investigation_run_id = :rid"), params
        )
        conn.execute(
            text("DELETE FROM investigation_runs WHERE investigation_run_id = :rid"),
            params,
        )
    else:
        conn.execute(text("DELETE FROM recommendations"))
        conn.execute(text("DELETE FROM findings"))
        conn.execute(text("DELETE FROM evidence"))
        conn.execute(text("DELETE FROM risk_signals"))
        conn.execute(text("DELETE FROM agent_runs"))
        conn.execute(text("DELETE FROM investigation_runs"))
