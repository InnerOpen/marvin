"""The migration that removes read:assets / read:resources from API clients (86af6abd02c3)."""

import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION = next((Path(__file__).resolve().parents[1] / "src/marvin/alembic/versions").glob("*_86af6abd02c3_*.py"))


def _load_migration():
    spec = importlib.util.spec_from_file_location("retired_permissions_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def db(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE api_clients (id VARCHAR PRIMARY KEY, permissions JSON NOT NULL)")
    yield engine
    engine.dispose()


def _insert(engine, **clients) -> None:
    with engine.begin() as conn:
        for client_id, permissions in clients.items():
            conn.exec_driver_sql("INSERT INTO api_clients (id, permissions) VALUES (?, ?)", (client_id, json.dumps(permissions)))


def _permissions(engine) -> dict:
    with engine.connect() as conn:
        return {row[0]: json.loads(row[1]) for row in conn.exec_driver_sql("SELECT id, permissions FROM api_clients")}


def _upgrade(engine) -> None:
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            _load_migration().upgrade()


def test_the_retired_keys_go_and_everything_else_stays(db):
    _insert(
        db,
        site={"read:published_entries": True, "read:assets": True, "read:resources": False, "read:collections": True},
        preview={"read:all_entries": True},
        only_retired={"read:assets": True},
    )
    _upgrade(db)
    assert _permissions(db) == {
        "site": {"read:published_entries": True, "read:collections": True},
        "preview": {"read:all_entries": True},
        "only_retired": {},
    }


def test_running_it_twice_changes_nothing_more(db):
    _insert(db, site={"read:published_entries": True, "read:assets": True})
    _upgrade(db)
    _upgrade(db)
    assert _permissions(db) == {"site": {"read:published_entries": True}}
