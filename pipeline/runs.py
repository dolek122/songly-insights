from sqlalchemy import Engine, text

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
