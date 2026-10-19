"""Jared's journey: a brand-new install on SQLite, end to end, in a Marvin process of its own (tests/fresh_install_driver.py)
with an empty DATA_DIR and no database settings at all (the auto rule picks SQLite).

    first start -> the bootstrapped admin signs in -> Admin creates a workspace -> imports the golden bundle
    -> counts, rows, files and decrypted secrets are all there

Then the whole-platform backup (the CLI job a CronJob runs): back up, restore into an empty directory, start Marvin on that
directory, and find the same installation: the same admin password, workspace, files and secrets (the restored `.secret`
is what decrypts them).
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from tests.golden_bundle import BUNDLE_PATH, GOLDEN, GOLDEN_BACKUP_KEY

REPO = Path(__file__).resolve().parents[1]
PASSWORD = "journey-password-1"


def _env(data_dir: Path, base: Path, **extra: str) -> dict[str, str]:
    """A bare container environment: nothing about a database, no .env (BASE_DIR is empty), DATA_DIR a new directory."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DB_", "POSTGRES_", "STORAGE_", "BACKUP_", "SECRET", "DEFAULT_"))}
    base.mkdir(exist_ok=True)
    env.update(
        PYTHONPATH=f"{REPO / 'src'}{os.pathsep}{REPO}", BASE_DIR=str(base), PRODUCTION="True", TESTING="False", DATA_DIR=str(data_dir),
        DEFAULT_PASSWORD=PASSWORD, EMBEDDINGS_BUILTIN_ENABLED="False", MEDIA_EMBEDS_FETCH_ENABLED="False", PLUGIN_UPDATE_CHECK="False",
        **extra,
    )  # fmt: skip
    env.pop("TESTING", None)
    return env


def _run(args: list[str], env: dict[str, str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], env=env, cwd=REPO, capture_output=True, text=True, timeout=timeout)


def _facts(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, f"{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def _assert_golden(facts: dict) -> None:
    c = GOLDEN["counts"]
    assert facts["workspace"] and facts["admin_logged_in"]
    assert (facts["entries"], facts["published_entries"], facts["resources"], facts["assets"]) == (c["entries"], 2, c["resources"], c["assets"])
    assert facts["collections"] >= c["collections"] and facts["tags"] >= c["tags"]
    assert facts["variables"] == GOLDEN["variables"]
    assert facts["secrets"] == GOLDEN["secrets"]  # decrypted with the backup key, and readable by the running app
    assert facts["files"] == GOLDEN["files"]  # the bytes, by sha256


@pytest.fixture(scope="module")
def install(tmp_path_factory):
    """The first start and the admin's steps, run once; the tests read what it left."""
    root = tmp_path_factory.mktemp("fresh")
    data = root / "data"  # does not exist yet: Marvin makes it
    env = _env(data, root / "base")
    facts = _facts(_run(["-m", "tests.fresh_install_driver", "journey", str(BUNDLE_PATH), GOLDEN_BACKUP_KEY], env))
    return type("Install", (), {"root": root, "data": data, "env": env, "facts": facts})


def test_first_start_creates_a_sqlite_file_and_one_admin(install):
    assert install.facts["engine"] == "sqlite"
    assert Path(install.facts["db_file"]) == install.data / "marvin.db" and (install.data / "marvin.db").is_file()
    assert (install.data / ".secret").is_file()
    assert install.facts["users"] == 1


def test_the_imported_bundle_is_all_there(install):
    c = GOLDEN["counts"]
    assert {k: install.facts["imported"][k] for k in c} == c and install.facts["imported"]["errors"] == 0
    _assert_golden(install.facts)


@pytest.mark.skipif(not Path("/dev/shm").is_dir(), reason="the backup target needs a second filesystem (/dev/shm)")
def test_full_platform_backup_and_restore_round_trip(install):
    import shutil

    nas = Path(tempfile.mkdtemp(dir="/dev/shm", prefix="marvin-journey-nas-"))
    try:
        job_env = {**install.env, "BACKUP_DATA_DIR": str(install.data), "BACKUP_LOCAL_ROOT": str(nas)}
        job_env.pop("DATA_DIR")
        backup = _run(["-m", "marvin.scripts.backup", "run", "--target", "local", "--name", "journey"], job_env)
        assert backup.returncode == 0, backup.stdout + backup.stderr
        assert "backup[journey] ok" in backup.stdout
        listed = _run(["-m", "marvin.scripts.backup", "list", "--target", "local"], job_env).stdout
        assert "sqlite/marvin-" in listed and "config/marvin-config-" in listed

        restored = install.root / "restored"
        done = _run(["-m", "marvin.scripts.backup", "restore", "--target", "local", "--into", str(restored)], job_env)
        assert done.returncode == 0, done.stdout + done.stderr
        assert (restored / "marvin.db").is_file() and (restored / ".secret").read_text() == (install.data / ".secret").read_text()
        assert not list(restored.glob("marvin.db-*")), "a restored database is one self-contained file"

        # Marvin starts on the restored directory and finds the installation it was backed up from.
        after = _facts(_run(["-m", "tests.fresh_install_driver", "inspect"], _env(restored, install.root / "base2")))
        assert after["engine"] == "sqlite" and Path(after["db_file"]) == restored / "marvin.db"
        assert after["users"] == 1
        _assert_golden(after)
    finally:
        shutil.rmtree(nas, ignore_errors=True)
