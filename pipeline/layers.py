from pathlib import Path

from sqlalchemy import Engine

SQL_DIR = Path(__file__).parent / "sql"


def run_sql_file(engine: Engine, file_name: str) -> None:
    sql = (SQL_DIR / file_name).read_text()
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)


def build_staging(engine: Engine) -> None:
    run_sql_file(engine, "staging.sql")


def build_marts(engine: Engine) -> None:
    run_sql_file(engine, "marts.sql")
