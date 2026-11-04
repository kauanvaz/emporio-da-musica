from pathlib import Path
from typing import Any
from urllib.parse import quote

from sqlalchemy import Engine, create_engine, event


def _enable_sqlite_foreign_keys(
    dbapi_connection: Any,
    connection_record: Any,
) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


def create_seed_engine(database_path: str | Path) -> Engine:
    engine = create_engine(f"sqlite:///{Path(database_path)}")
    event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def create_runtime_engine(database_path: str | Path) -> Engine:
    encoded_path = quote(str(Path(database_path)), safe="/")
    return create_engine(f"sqlite:///file:{encoded_path}?mode=ro&uri=true")


__all__ = ["create_runtime_engine", "create_seed_engine"]
