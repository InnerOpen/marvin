"""A fresh install creates no workspace (tasks/retire-platform-workspace-plan.md, decisions 2026-10-18).

Each case starts Marvin in a process of its own on an empty database (tests/fresh_install_driver.py ``first_boot``),
on SQLite and, when the suite itself runs on PostgreSQL, on a scratch PostgreSQL database: the first super admin
exists and can sign in and use Admin; no workspace, membership or home exists; demo mode creates its sample users but
still no workspace; a second start changes nothing; and the retired ``DEFAULT_GROUP`` only draws a startup warning.
"""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from tests.test_fresh_install_journey import REPO, _env

SUITE_ENGINE = os.environ.get("DB_ENGINE", "sqlite").strip().lower() or "sqlite"


def _postgres_admin():
    import psycopg2

    return psycopg2.connect(
        host=os.environ.get("POSTGRES_SERVER", "127.0.0.1"),
        port=os.environ.get("POSTGRES_PORT", "5434"),
        user=os.environ.get("POSTGRES_USER", "default"),
        password=os.environ.get("POSTGRES_PASSWORD", "default"),
        dbname="postgres",
    )


@pytest.fixture(params=["sqlite", "postgres"])
def database(request, tmp_path):
    """Environment settings pointing the child process at an empty database of its own."""
    if request.param == "sqlite":
        yield {}
        return
    if SUITE_ENGINE != "postgres":
        pytest.skip("PostgreSQL case runs with DB_ENGINE=postgres (the suite's own engine)")
    name = f"marvin_test_fresh_{uuid.uuid4().hex[:8]}"
    conn = _postgres_admin()
    conn.autocommit = True
    conn.cursor().execute(f'CREATE DATABASE "{name}"')
    try:
        yield {
            "DB_ENGINE": "postgres",
            "POSTGRES_DB": name,
            "POSTGRES_SERVER": os.environ.get("POSTGRES_SERVER", "127.0.0.1"),
            "POSTGRES_PORT": os.environ.get("POSTGRES_PORT", "5434"),
            "POSTGRES_USER": os.environ.get("POSTGRES_USER", "default"),
            "POSTGRES_PASSWORD": os.environ.get("POSTGRES_PASSWORD", "default"),
        }
    finally:
        cur = conn.cursor()
        cur.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        conn.close()


def _first_boot(tmp_path: Path, database: dict, **extra: str) -> tuple[dict, str]:
    env = {**_env(tmp_path / "data", tmp_path / "base", **extra), **database}
    result = subprocess.run(
        [sys.executable, "-m", "tests.fresh_install_driver", "first_boot"], env=env, cwd=REPO, capture_output=True, text=True, timeout=300
    )
    assert result.returncode == 0, f"{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1]), result.stdout + result.stderr


def test_first_start_has_an_admin_and_no_workspace(tmp_path, database):
    facts, _ = _first_boot(tmp_path, database)
    assert facts["engine"] == {"postgres": "postgresql"}.get(database.get("DB_ENGINE", "sqlite"), "sqlite")
    assert (facts["users"], facts["groups"], facts["memberships"]) == (1, 0, 0)
    assert facts["admin_home"] is None and "SUPER_ADMIN" in facts["admin_role"]
    # The admin signed in (the driver's login asserted it) and Admin works with zero workspaces.
    assert facts["about_status"] == 200
    assert (facts["admin_groups_status"], facts["admin_groups_total"]) == (200, 0)
    assert (facts["current_status"], facts["current"]) == (200, None)
    assert facts["workspace_page_status"] == 409  # workspace pages say "no_workspace", not an error page
    assert (facts["groups_after_restart"], facts["users_after_restart"]) == (0, 1)


def test_demo_mode_creates_its_users_but_no_workspace(tmp_path, database):
    facts, _ = _first_boot(tmp_path, database, IS_DEMO="True")
    assert facts["users"] == 5 and facts["groups"] == 0 and facts["memberships"] == 0
    assert facts["homes"] == [None] * 5


def test_retired_default_group_warns_and_changes_nothing(tmp_path, database):
    facts, output = _first_boot(tmp_path, database, DEFAULT_GROUP="Marvin Admin")
    assert facts["groups"] == 0
    assert "DEFAULT_GROUP is set but no longer used" in output


def test_no_default_group_no_warning(tmp_path, database):
    _, output = _first_boot(tmp_path, database)
    assert "DEFAULT_GROUP" not in output
