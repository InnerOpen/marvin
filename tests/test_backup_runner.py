"""Starting a backup target's run from a scheduled task (services/backup_runner.py, handlers/backups.py):
a Job from the target's CronJob on Kubernetes, a child process elsewhere — never the backup itself."""

import json
from types import SimpleNamespace

import httpx
import pytest

from marvin.services import backup_runner
from marvin.services.backup_runner import BackupRunnerError, KubernetesRunner, job_from_cronjob
from marvin.services.scheduled_tasks.handlers.backups import RunBackupTargetHandler

CRONJOB = {
    "metadata": {"name": "marvin-backup-r2", "uid": "u-1"},
    "spec": {
        "schedule": "0 * * * *",
        "jobTemplate": {
            "metadata": {"labels": {"app.kubernetes.io/component": "backup", "marvin.backup/target": "r2"}},
            "spec": {
                "backoffLimit": 2,
                "template": {
                    "spec": {
                        "restartPolicy": "Never",
                        "containers": [
                            {
                                "name": "backup",
                                "args": ["run", "--target", "s3", "--name", "r2"],
                                "env": [{"name": "BACKUP_SCHEDULE", "value": "0 * * * *"}, {"name": "DB_ENGINE", "value": "postgres"}],
                            }
                        ],
                    }
                },
            },
        },
    },
}


def test_targets_are_names_with_an_optional_type():
    assert backup_runner.parse_targets(" r2:s3, nas-nightly:local ,offsite,") == {"r2": "s3", "nas-nightly": "local", "offsite": "offsite"}


def test_a_job_from_the_cronjob_is_its_template_with_our_label_ttl_and_schedule():
    job = job_from_cronjob(CRONJOB, "r2", {"BACKUP_SCHEDULE": "30 2 * * *"}, suffix="m123")

    assert job["metadata"]["name"] == "marvin-backup-r2-m123"
    assert job["metadata"]["labels"]["marvin.backup/target"] == "r2"
    assert job["metadata"]["annotations"]["cronjob.kubernetes.io/instantiate"] == "manual"
    assert job["spec"]["ttlSecondsAfterFinished"] == backup_runner.JOB_TTL_SECONDS
    env = job["spec"]["template"]["spec"]["containers"][0]["env"]
    assert {var["name"]: var["value"] for var in env} == {"DB_ENGINE": "postgres", "BACKUP_SCHEDULE": "30 2 * * *"}
    # the CronJob's own template is left as it was
    assert CRONJOB["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["env"][0]["value"] == "0 * * * *"


@pytest.fixture
def account(tmp_path):
    (tmp_path / "token").write_text("sa-token\n")
    (tmp_path / "namespace").write_text("marvin\n")
    return tmp_path


def _cluster(account, *, active=False, status=None):
    """A fake API server; returns (runner, the requests it saw)."""
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["Authorization"] == "Bearer sa-token"
        if status:
            return httpx.Response(status, text="no")
        path = request.url.path
        if request.method == "GET" and path.endswith("/jobs"):
            items = [{"metadata": {"name": "marvin-backup-r2-29861000"}, "status": {"active": 1}}] if active else []
            return httpx.Response(200, json={"items": items})
        if request.method == "GET" and path.endswith("/cronjobs/marvin-backup-r2"):
            return httpx.Response(200, json=CRONJOB)
        if request.method == "POST" and path.endswith("/jobs"):
            return httpx.Response(201, json=json.loads(request.content))
        return httpx.Response(404, text="not found")

    runner = KubernetesRunner(account=account, host="https://k8s.test", transport=httpx.MockTransport(handle))
    return runner, seen


def test_kubernetes_runner_creates_a_job_in_its_own_namespace(account):
    runner, seen = _cluster(account)

    started = runner.start("marvin-backup-r2", "r2", {})

    assert started.detail.startswith("Job marvin-backup-r2-m") and not started.already_running
    assert seen[0].url.params["labelSelector"] == "marvin.backup/target=r2"
    assert [(r.method, r.url.path) for r in seen] == [
        ("GET", "/apis/batch/v1/namespaces/marvin/jobs"),
        ("GET", "/apis/batch/v1/namespaces/marvin/cronjobs/marvin-backup-r2"),
        ("POST", "/apis/batch/v1/namespaces/marvin/jobs"),
    ]


def test_a_target_already_running_is_not_started_twice(account):
    runner, seen = _cluster(account, active=True)

    started = runner.start("marvin-backup-r2", "r2", {})

    assert started.already_running and "29861000" in started.detail
    assert all(r.method == "GET" for r in seen)


def test_without_the_role_the_error_says_what_to_turn_on(account):
    runner, _ = _cluster(account, status=403)
    with pytest.raises(BackupRunnerError, match=r"backup\.scheduledTasks\.enabled"):
        runner.start("marvin-backup-r2", "r2", {})


def test_outside_kubernetes_the_runner_says_so(tmp_path):
    with pytest.raises(BackupRunnerError, match="running in Kubernetes"):
        KubernetesRunner(account=tmp_path / "nowhere")


def test_process_runner_starts_the_backup_script_once_per_target(monkeypatch):
    started = []

    class FakeChild:
        pid = 4242

        def __init__(self, args, env, start_new_session):
            started.append((args, env))

        def poll(self):
            return None  # still running

        def wait(self):
            return 0

    monkeypatch.setattr(backup_runner.subprocess, "Popen", FakeChild)
    monkeypatch.setattr(backup_runner, "_children", {})

    first = backup_runner.start_process("nas", "local", {"BACKUP_SCHEDULE": "30 2 * * *"})
    second = backup_runner.start_process("nas", "local", {})

    assert first.detail == "pid 4242" and second.already_running
    ((args, env),) = started
    assert args[1:] == ["-m", "marvin.scripts.backup", "run", "--target", "local", "--name", "nas"]
    assert env["BACKUP_SCHEDULE"] == "30 2 * * *"


def _settings(monkeypatch, **values):
    from marvin.core import config

    settings = SimpleNamespace(BACKUP_RUNNER="kubernetes", BACKUP_TARGETS="r2:s3", BACKUP_CRONJOB_PREFIX="marvin-backup-")
    for key, value in values.items():
        setattr(settings, key, value)
    monkeypatch.setattr(config, "get_app_settings", lambda: settings)


def _task(enabled=True, schedule_type="interval", schedule_config=None, target="r2"):
    return SimpleNamespace(
        group_id=None, enabled=enabled, schedule_type=schedule_type, schedule_config=schedule_config or {}, task_config={"target": target}
    )


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_start(runner, name, kind, env, *, cronjob_prefix=""):
        seen.append(SimpleNamespace(runner=runner, name=name, kind=kind, env=env, prefix=cronjob_prefix))
        return backup_runner.Started(name, "Job marvin-backup-r2-m1")

    monkeypatch.setattr(backup_runner, "start", fake_start)
    return seen


def test_handler_starts_the_target_and_points_at_backup_health(monkeypatch, calls):
    _settings(monkeypatch)

    summary = RunBackupTargetHandler().execute(_task(), None)

    assert summary == "Started backup r2 (Job marvin-backup-r2-m1); its result appears in Admin → Backup health"
    assert (calls[0].runner, calls[0].kind, calls[0].prefix, calls[0].env) == ("kubernetes", "s3", "marvin-backup-", {})


def test_an_enabled_cron_task_owns_the_schedule_the_run_records(monkeypatch, calls):
    _settings(monkeypatch)
    cron = {"cron_expression": "30 2 * * *", "timezone": "America/New_York"}

    RunBackupTargetHandler().execute(_task(schedule_type="cron", schedule_config=cron), None)
    RunBackupTargetHandler().execute(_task(enabled=False, schedule_type="cron", schedule_config=cron), None)

    assert calls[0].env == {"BACKUP_SCHEDULE": "30 2 * * *", "BACKUP_TIME_ZONE": "America/New_York"}
    assert calls[1].env == {}  # Run Now only: the CronJob's schedule stays the one recorded


def test_handler_refuses_when_not_set_up_or_the_target_is_unknown(monkeypatch, calls):
    _settings(monkeypatch, BACKUP_RUNNER="")
    with pytest.raises(ValueError, match="BACKUP_RUNNER is not set"):
        RunBackupTargetHandler().execute(_task(), None)

    _settings(monkeypatch)
    with pytest.raises(ValueError, match=r"Unknown backup target 'nas' \(configured: r2\)"):
        RunBackupTargetHandler().execute(_task(target="nas"), None)
    assert calls == []
