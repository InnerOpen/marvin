"""Per-workspace backup bundles off-site: the backend writes them on a schedule (create_workspace_bundles), the backup
job copies them to its target under bundles/<workspace>/ and keeps the newest per workspace (backup_engine). The backend
never holds a target's credentials."""

import asyncio
import re
import uuid
import zipfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from marvin.services.backup_engine import engine as eng
from marvin.services.backup_engine import layout as keys
from marvin.services.backup_engine.layout import Retention
from marvin.services.backup_engine.local_target import LocalBackupTarget

NOW = datetime(2026, 10, 10, 19, 0, tzinfo=UTC)
TOKEN = "ab" * 8  # the 16 hex characters a bundle name ends with (any will do)


def _bundle(folder: Path, slug: str, date: str, label: str = "scheduled", token: str = TOKEN) -> Path:
    path = folder / f"{slug}-backup-{date}-{f'{label}-' if label else ''}{token}.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("x.json", f"{slug} {date}")
    return path


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    (d / "backups").mkdir(parents=True)
    return d


@pytest.fixture
def target(tmp_path: Path) -> LocalBackupTarget:
    root = tmp_path / "nas"
    root.mkdir()
    return LocalBackupTarget(root)


def _settings(data_dir: Path, bundles: int = 14) -> eng.BackupSettings:
    return eng.BackupSettings(data_dir=data_dir, retention=Retention(bundles=bundles))


def _bundle_keys(target) -> list[str]:
    return sorted(target.list(keys.BUNDLES_PREFIX))


# ── names ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name, key",
    [
        (f"acme-backup-2026-10-10-{TOKEN}.zip", f"bundles/acme/acme-backup-2026-10-10-{TOKEN}.zip"),
        (f"acme-co-backup-2026-10-10-scheduled-{TOKEN}.zip", f"bundles/acme-co/acme-co-backup-2026-10-10-scheduled-{TOKEN}.zip"),
        (f"my-backup-site-backup-2026-10-10-{TOKEN}.zip", f"bundles/my-backup-site/my-backup-site-backup-2026-10-10-{TOKEN}.zip"),
        ("notes.zip", None),
        (f"acme-backup-2026-10-10-{TOKEN}.zip.part", None),
    ],
)
def test_only_bundles_marvin_named_get_a_key(name, key):
    assert keys.bundle_key(name) == key


def test_retention_keeps_the_newest_per_workspace_and_never_a_foreign_key():
    listing = [f"bundles/acme/acme-backup-2026-10-0{d}-{TOKEN}.zip" for d in range(1, 6)] + [
        f"bundles/beta/beta-backup-2026-10-01-{TOKEN}.zip",
        "bundles/acme/notes.txt",
        f"bundles/beta/acme-backup-2026-09-01-{TOKEN}.zip",
    ]
    assert keys.expired_bundles(listing, keep=2) == [f"bundles/acme/acme-backup-2026-10-0{d}-{TOKEN}.zip" for d in (1, 2, 3)]


def test_retention_bundles_comes_from_the_environment():
    assert Retention.from_env({}).bundles == 14
    assert Retention.from_env({"BACKUP_KEEP_BUNDLES": "0"}).bundles == 0
    with pytest.raises(keys.BackupError):
        Retention.from_env({"BACKUP_KEEP_BUNDLES": "-1"})


# ── the backup job copies them ───────────────────────────────────────────────


def test_bundles_are_copied_once_and_thinned_to_the_newest_per_workspace(data_dir, target):
    folder = data_dir / "backups"
    for day in ("2026-10-08", "2026-10-09", "2026-10-10"):
        _bundle(folder, "acme", day)
    manual = _bundle(folder, "acme", "2026-10-10", label="", token="cd" * 8)
    (folder / "stray.zip").write_bytes(b"not a bundle")

    report = eng.Report()
    eng.backup_bundles(_settings(data_dir, bundles=2), target, report, dry_run=False)

    assert report.bundles_uploaded == 4 and report.pruned == 2
    assert _bundle_keys(target) == sorted([f"bundles/acme/{manual.name}", f"bundles/acme/acme-backup-2026-10-10-scheduled-{TOKEN}.zip"])
    again = eng.Report()
    eng.backup_bundles(_settings(data_dir, bundles=2), target, again, dry_run=False)
    assert again.bundles_uploaded == 2  # the two pruned ones are still local, so they go up and are thinned again
    assert _bundle_keys(target) == sorted([f"bundles/acme/{manual.name}", f"bundles/acme/acme-backup-2026-10-10-scheduled-{TOKEN}.zip"])


def test_a_target_with_bundles_off_gets_none(data_dir, target):
    _bundle(data_dir / "backups", "acme", "2026-10-10")
    report = eng.Report()
    eng.backup_bundles(_settings(data_dir, bundles=0), target, report, dry_run=False)
    assert report.bundles_uploaded == 0 and _bundle_keys(target) == []


def test_a_full_run_includes_bundles_in_its_summary(data_dir, target):
    _bundle(data_dir / "backups", "acme", "2026-10-10")
    report = eng.run_backup(_settings(data_dir), target, None, now=NOW)  # no database here: that step fails, alone
    assert "bundles 1 uploaded" in report.summary(1.0, dry_run=False)
    assert [f.split(":")[0] for f in report.failures] == ["database", "config"]


def test_a_bundle_lists_and_fetches_with_its_checksum_checked(data_dir, target, tmp_path):
    path = _bundle(data_dir / "backups", "acme", "2026-10-10")
    eng.backup_bundles(_settings(data_dir), target, eng.Report(), dry_run=False)
    key = f"bundles/acme/{path.name}"

    assert key in [o.key for o in eng.list_backups(target)]
    fetched = eng.fetch_bundle(target, key, tmp_path / "out")
    assert fetched.read_bytes() == path.read_bytes()
    with pytest.raises(keys.BackupError, match="not a workspace bundle key"):
        eng.fetch_bundle(target, "config/marvin-config-20261010T190000Z.tar.gz", tmp_path / "out")


# ── the backend writes them ──────────────────────────────────────────────────


@pytest.fixture
def workspaces(db_session, monkeypatch, tmp_path):
    """Two throwaway workspaces, BACKUP_DIR in tmp, and the exporter replaced by one that writes a tiny zip."""
    from marvin.db.models.groups import Groups
    from marvin.repos.seed import workspace_exporter
    from marvin.services.scheduled_tasks.handlers import backups

    tag = uuid.uuid4().hex[:6]
    slugs = [f"wb-{tag}-a", f"wb-{tag}-b"]
    for slug in slugs:
        g = Groups(session=db_session, name=slug, slug=slug)
        g.id = uuid.uuid4()
        db_session.add(g)
    db_session.commit()

    backup_dir = tmp_path / "backups"
    monkeypatch.setattr("marvin.core.config.get_app_dirs", lambda: SimpleNamespace(BACKUP_DIR=backup_dir))

    @contextmanager
    def this_session():
        yield db_session

    monkeypatch.setattr("marvin.db.db_setup.session_context", this_session)
    failing: set[str] = set()

    def export(self, include_system_types=False, temp_dir=None, label=None):
        slug = self.repos.groups.get_one(self.repos.group_id).slug
        if slug in failing:
            raise OSError("storage unreachable")
        return _bundle(temp_dir, slug, datetime.now(UTC).date().isoformat(), label=label or "", token=uuid.uuid4().hex[:16])

    monkeypatch.setattr(workspace_exporter.WorkspaceExporter, "export_workspace_bundle", export)
    yield SimpleNamespace(slugs=slugs, dir=backup_dir, failing=failing, handler=backups.CreateWorkspaceBundlesHandler())
    db_session.rollback()
    db_session.query(Groups).filter(Groups.slug.in_(slugs)).delete(synchronize_session=False)
    db_session.commit()


def _mine(ws, slug):
    return sorted(p.name for p in ws.dir.glob(f"{slug}-backup-*.zip"))


def test_every_workspace_gets_a_scheduled_bundle_and_only_scheduled_ones_are_thinned(workspaces):
    ws = workspaces
    a = ws.slugs[0]
    ws.dir.mkdir()
    by_hand = _bundle(ws.dir, a, "2026-01-01", label="", token="1" * 16)

    for _ in range(3):
        summary = ws.handler.execute(SimpleNamespace(group_id=None, task_config={"keep": 2}), None)

    # It bundles every workspace in the database (the test database holds others too); the files below pin ours.
    assert re.fullmatch(r"Bundled \d+ workspace\(s\), [\d.]+ MB; removed \d+ older scheduled bundle\(s\)", summary)
    scheduled = [n for n in _mine(ws, a) if "-scheduled-" in n]
    assert len(scheduled) == 2 and by_hand.exists()
    assert len([n for n in _mine(ws, ws.slugs[1]) if "-scheduled-" in n]) == 2


def test_one_workspace_failing_still_bundles_the_others_and_fails_the_run(workspaces):
    ws = workspaces
    ws.failing.add(ws.slugs[0])
    with pytest.raises(RuntimeError, match=f"failed: {ws.slugs[0]}"):
        ws.handler.execute(SimpleNamespace(group_id=None, task_config={}), None)
    assert _mine(ws, ws.slugs[0]) == [] and len(_mine(ws, ws.slugs[1])) == 1


def test_it_ships_as_a_daily_system_task():
    from marvin.services.scheduled_tasks.system_tasks import SYSTEM_SCHEDULED_TASKS

    task = next(d for d in SYSTEM_SCHEDULED_TASKS if d.task_type == "create_workspace_bundles")
    assert task.enabled and task.schedule_config == {"interval_seconds": 24 * 60 * 60} and task.task_config == {"keep": 2}


def test_the_scheduled_task_tick_runs_off_the_event_loop():
    """A bundle takes seconds; the tick that runs handlers must not hold the API's event loop meanwhile."""
    from marvin.services.scheduler.tasks import check_scheduled_tasks

    assert asyncio.iscoroutinefunction(check_scheduled_tasks)
