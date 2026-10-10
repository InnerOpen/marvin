"""Start a backup target's run from the backend — the `run_backup_target` scheduled task.

Two ways, chosen by BACKUP_RUNNER:

- ``kubernetes`` (option B): create a one-off Job from the target's CronJob, as ``kubectl create job --from=
  cronjob/...`` does. The CronJob stays the single definition of the backup pod — its image, volumes,
  credentials (a Secret the backend never sees) and node — so the backend only needs to read CronJobs and
  create/list Jobs in its own namespace (the chart's Role, backup.scheduledTasks.enabled).
- ``process`` (option A, installs without Kubernetes): run ``python -m marvin.scripts.backup run`` as a child
  of the backend. The target's settings and credentials must then be in the backend's own environment, a
  backup competes with the live site for CPU and I/O, and no backup runs while the backend is down.

Either way this only *starts* the run and returns: a scheduled run is executed on the API's event loop, and a
backup takes minutes. The run records itself in ``backup_runs`` exactly like a CronJob run (backup_engine/
recorder.py), so Admin → Backup health and the backup alerts see it.

BACKUP_TARGETS lists the targets this backend may start, ``name`` or ``name:type`` (type defaults to the
name), comma separated; a target that isn't listed is refused.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

KUBERNETES = "kubernetes"
PROCESS = "process"
TARGET_LABEL = "marvin.backup/target"  # on every Job of a target, the CronJob's and ours (chart jobTemplate)
JOB_TTL_SECONDS = 24 * 60 * 60  # a Job we create isn't the CronJob's to clean up, so it removes itself
SERVICE_ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")
API_TIMEOUT = 15  # seconds


class BackupRunnerError(Exception):
    """The run could not be started (configuration, permissions, the cluster API)."""


@dataclass(frozen=True)
class Started:
    target: str
    detail: str  # the Job's name, or the child's pid
    already_running: bool = False


def parse_targets(spec: str) -> dict[str, str]:
    """``"r2, nas-nightly:local"`` → ``{"r2": "r2", "nas-nightly": "local"}`` (name → type)."""
    targets = {}
    for item in filter(None, (part.strip() for part in spec.split(","))):
        name, _, kind = item.partition(":")
        targets[name.strip()] = kind.strip() or name.strip()
    return targets


def schedule_env(schedule: str | None, time_zone: str | None) -> dict[str, str]:
    """BACKUP_SCHEDULE / BACKUP_TIME_ZONE for the run to record, when Marvin owns the target's schedule."""
    env = {}
    if schedule:
        env["BACKUP_SCHEDULE"] = schedule
        if time_zone:
            env["BACKUP_TIME_ZONE"] = time_zone
    return env


def start(runner: str, name: str, kind: str, env: dict[str, str], *, cronjob_prefix: str = "") -> Started:
    if runner == KUBERNETES:
        if not cronjob_prefix:
            raise BackupRunnerError("BACKUP_CRONJOB_PREFIX is not set (the chart sets it with backup.scheduledTasks.enabled)")
        return KubernetesRunner().start(f"{cronjob_prefix}{name}", name, env)
    if runner == PROCESS:
        return start_process(name, kind, env)
    raise BackupRunnerError(f"BACKUP_RUNNER is {runner!r}: expected {KUBERNETES!r} or {PROCESS!r}")


# --- option A: a child process ------------------------------------------------------------------------------

_children: dict[str, subprocess.Popen] = {}
_children_lock = threading.Lock()


def start_process(name: str, kind: str, env: dict[str, str]) -> Started:
    with _children_lock:
        running = _children.get(name)
        if running is not None and running.poll() is None:
            return Started(name, f"pid {running.pid}", already_running=True)
        child = subprocess.Popen(
            [sys.executable, "-m", "marvin.scripts.backup", "run", "--target", kind, "--name", name],
            env={**os.environ, **env},
            start_new_session=True,  # its own process group: a signal meant for the backend's workers skips it
        )
        _children[name] = child
    # Reap it when it ends (no zombie), and say how it went; the run's details are in backup_runs.
    threading.Thread(target=_reap, args=(name, child), daemon=True, name=f"backup-{name}").start()
    logger.info("Backup %s: started (pid %s)", name, child.pid)
    return Started(name, f"pid {child.pid}")


def _reap(name: str, child: subprocess.Popen) -> None:
    code = child.wait()
    log = logger.info if code == 0 else logger.warning
    log("Backup %s: process %s exited %s", name, child.pid, code)


# --- option B: a Kubernetes Job from the target's CronJob ---------------------------------------------------


class KubernetesRunner:
    """The in-cluster API with the pod's service-account token: one GET, one LIST, one POST."""

    def __init__(self, account: Path = SERVICE_ACCOUNT, host: str | None = None, transport: httpx.BaseTransport | None = None):
        try:
            token = (account / "token").read_text().strip()
            self.namespace = (account / "namespace").read_text().strip()
        except OSError as e:
            raise BackupRunnerError(f"no service-account token in {account}: is this backend running in Kubernetes?") from e
        if host is None:
            api_host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
            host = f"https://{api_host}:{os.environ.get('KUBERNETES_SERVICE_PORT', '443')}"
        ca = account / "ca.crt"
        self.client = httpx.Client(
            base_url=f"{host}/apis/batch/v1/namespaces/{self.namespace}",
            headers={"Authorization": f"Bearer {token}"},
            verify=str(ca) if ca.exists() and transport is None else True,
            timeout=API_TIMEOUT,
            transport=transport,
        )

    def start(self, cronjob_name: str, target: str, env: dict[str, str]) -> Started:
        with self.client:
            active = self._active_job(target)
            if active:
                return Started(target, active, already_running=True)
            cronjob = self._call("GET", f"/cronjobs/{cronjob_name}")
            job = job_from_cronjob(cronjob, target, env, suffix=f"m{int(time.time()) % 10**9}")
            created = self._call("POST", "/jobs", json=job)
        name = created["metadata"]["name"]
        logger.info("Backup %s: started Job %s", target, name)
        return Started(target, f"Job {name}")

    def _active_job(self, target: str) -> str | None:
        jobs = self._call("GET", "/jobs", params={"labelSelector": f"{TARGET_LABEL}={target}"})
        for job in jobs.get("items", []):
            if (job.get("status") or {}).get("active"):
                return f"Job {job['metadata']['name']}"
        return None

    def _call(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise BackupRunnerError(f"the Kubernetes API did not answer: {e}") from e
        if response.status_code == 403:
            raise BackupRunnerError(
                f"{method} {path} was refused (403): the backend's service account needs the chart's backup Role (backup.scheduledTasks.enabled)"
            )
        if response.status_code == 404 and path.startswith("/cronjobs/"):
            raise BackupRunnerError(f"no CronJob {path.rsplit('/', 1)[-1]} in {self.namespace}: is the target in backup.targets?")
        if response.is_error:
            raise BackupRunnerError(f"{method} {path}: {response.status_code} {response.text[:200]}")
        return response.json()


def job_from_cronjob(cronjob: dict, target: str, env: dict[str, str], suffix: str) -> dict:
    """The Job ``kubectl create job --from=cronjob/<name>`` would make, plus our label, a TTL and ``env``."""
    template = cronjob["spec"]["jobTemplate"]
    spec = dict(template.get("spec") or {})
    spec.setdefault("ttlSecondsAfterFinished", JOB_TTL_SECONDS)
    if env:
        spec["template"] = _with_env(spec["template"], env)
    metadata = template.get("metadata") or {}
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": f"{cronjob['metadata']['name']}-{suffix}",
            "labels": {**(metadata.get("labels") or {}), TARGET_LABEL: target, "marvin.backup/trigger": "scheduled-task"},
            "annotations": {**(metadata.get("annotations") or {}), "cronjob.kubernetes.io/instantiate": "manual"},
        },
        "spec": spec,
    }


def _with_env(pod_template: dict, env: dict[str, str]) -> dict:
    """The pod template with ``env`` set (replacing same-named variables) on every container."""
    pod_spec = dict(pod_template["spec"])
    containers = []
    for container in pod_spec["containers"]:
        kept = [var for var in container.get("env") or [] if var.get("name") not in env]
        containers.append({**container, "env": kept + [{"name": k, "value": v} for k, v in env.items()]})
    pod_spec["containers"] = containers
    return {**pod_template, "spec": pod_spec}
