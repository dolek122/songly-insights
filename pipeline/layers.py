"""Builds the staging and marts layers from the SQL files in pipeline/sql/."""

from pathlib import Path

from sqlalchemy import Engine

SQL_DIR = Path(__file__).parent / "sql"


def run_sql_file(engine: Engine, file_name: str) -> None:
    """Run every statement of a SQL file in ONE transaction.

    `engine.begin()` commits at the end or rolls everything back on error, so a failed
    build leaves the previous version of the layer untouched. exec_driver_sql sends the
    file as it is; PostgreSQL accepts many statements in one call when there are no
    parameters.
    """
    sql = (SQL_DIR / file_name).read_text()
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)


def build_staging(engine: Engine) -> None:
    run_sql_file(engine, "staging.sql")


def build_marts(engine: Engine) -> None:
    run_sql_file(engine, "marts.sql")
