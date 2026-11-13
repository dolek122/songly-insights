"""History of pipeline runs in ops.pipeline_runs (ADR 0014).

Monitoring reads the newest row: did the last run succeed, when was the last success,
how many data quality checks failed. Writes happen in their own short transactions,
so a failed run is recorded even though its own changes were rolled back.
"""

from sqlalchemy import Engine, text

# Long error messages (stack traces) are cut: the full text is in the Prefect logs.
MAX_ERROR_LENGTH = 2000


def start_run(engine: Engine, flow_run_id: str) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text("INSERT INTO ops.pipeline_runs (flow_run_id) VALUES (:id) RETURNING id"),
            {"id": flow_run_id},
        ).scalar_one()


def finish_run(
    engine: Engine,
    run_id: int,
    status: str,
    dq_warnings: int,
    dq_errors: int,
    error: str | None = None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE ops.pipeline_runs
                SET finished_at = now(), status = :status, dq_warnings = :warnings,
                    dq_errors = :errors, error = :error
                WHERE id = :id
                """
            ),
            {
                "id": run_id,
                "status": status,
                "warnings": dq_warnings,
                "errors": dq_errors,
                "error": error[:MAX_ERROR_LENGTH] if error else None,
            },
        )
