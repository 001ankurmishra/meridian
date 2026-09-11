"""Agent run tracking logic."""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from sqlalchemy import Engine, text

T = TypeVar("T")


def record_agent_run(
    engine: Engine,
    investigation_run_id: uuid.UUID,
    agent_name: str,
    fn: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T:
    """Wrap an agent invocation to record its execution in the database.

    Args:
        investigation_run_id: UUID of the investigation run.
        agent_name: Name of the agent (e.g., 'TransactionAgent').
        fn: The agent function to invoke.
        *args: Positional arguments to pass to fn.
        **kwargs: Keyword arguments to pass to fn.

    Returns:
        The exact return value of the wrapped function fn.

    Raises:
        Any exception raised by fn is propagated exactly as-is to the caller.

    Side effects:
        Inserts exactly one row into the `agent_runs` table indicating the
        run's status ('SUCCESS' or 'FAILED') and timestamps.
    """
    agent_run_id = uuid.uuid4()
    started_at = datetime.now(timezone.utc)

    try:
        result = fn(*args, **kwargs)
        completed_at = datetime.now(timezone.utc)

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO agent_runs (
                        agent_run_id,
                        investigation_run_id,
                        agent_name,
                        tool_calls,
                        status,
                        model_identifier,
                        prompt_version,
                        started_at,
                        completed_at,
                        error
                    ) VALUES (
                        :agent_run_id,
                        :investigation_run_id,
                        :agent_name,
                        :tool_calls,
                        'SUCCESS',
                        NULL,
                        NULL,
                        :started_at,
                        :completed_at,
                        NULL
                    )
                    """
                ),
                {
                    "agent_run_id": agent_run_id,
                    "investigation_run_id": investigation_run_id,
                    "agent_name": agent_name,
                    "tool_calls": json.dumps({}),
                    "started_at": started_at,
                    "completed_at": completed_at,
                },
            )
        return result

    except Exception as e:
        completed_at = datetime.now(timezone.utc)
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO agent_runs (
                        agent_run_id,
                        investigation_run_id,
                        agent_name,
                        tool_calls,
                        status,
                        model_identifier,
                        prompt_version,
                        started_at,
                        completed_at,
                        error
                    ) VALUES (
                        :agent_run_id,
                        :investigation_run_id,
                        :agent_name,
                        :tool_calls,
                        'FAILED',
                        NULL,
                        NULL,
                        :started_at,
                        :completed_at,
                        :error
                    )
                    """
                ),
                {
                    "agent_run_id": agent_run_id,
                    "investigation_run_id": investigation_run_id,
                    "agent_name": agent_name,
                    "tool_calls": json.dumps({}),
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "error": str(e),
                },
            )
        raise
