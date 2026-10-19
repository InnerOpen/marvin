"""Deploys let in-flight AI runs finish: the server drains on SIGTERM and the chart gives it time.

An agent run is one synchronous request; a rollout restart used to kill the pod 30 s (the k8s
default) after SIGTERM, mid-run. The chart now sets a grace period and derives the server's drain
timeout and the interrupted-run sweep delay from it. The chart test needs the `helm` binary.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CHART = Path(__file__).resolve().parents[1] / "marvin-chart"


def test_server_passes_the_graceful_shutdown_timeout_to_uvicorn(monkeypatch):
    import marvin.app as app_mod

    seen = {}
    monkeypatch.setattr(app_mod.uvicorn, "run", lambda *a, **kw: seen.update(kw))
    monkeypatch.setattr(app_mod.settings, "GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS", 280)
    app_mod.main()
    assert seen["timeout_graceful_shutdown"] == 280


def _backend_pod(*args: str) -> dict:
    # Postgres: these are the rolling-update numbers (a SQLite release always recreates; tested below).
    out = subprocess.run(
        ["helm", "template", "t", str(CHART), "--set", "config.dbEngine=postgres", "--set", "postgres.cluster.enabled=true", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    deployments = [d for d in yaml.safe_load_all(out) if d and d.get("kind") == "Deployment"]
    backend = next(d for d in deployments if d["metadata"]["name"] in ("t-marvin", "t-marvin-backend"))
    return backend["spec"]["template"]["spec"]


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
@pytest.mark.parametrize("mode", ["combined", "split"])
def test_chart_backend_gets_grace_period_prestop_and_matching_timeouts(mode):
    pod = _backend_pod("--set", f"mode={mode}")
    container = pod["containers"][0]
    env = {e["name"]: e.get("value") for e in container["env"]}
    assert pod["terminationGracePeriodSeconds"] == 300
    assert container["lifecycle"]["preStop"]["exec"]["command"] == ["sleep", "5"]
    assert env["GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS"] == "280"  # 300 - 5 preStop - 15 exit margin
    assert env["AI_INTERRUPTED_RUN_SWEEP_DELAY_SECONDS"] == "360"  # past the old pod's kill deadline


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
def test_chart_prestop_can_be_turned_off():
    pod = _backend_pod("--set", "shutdown.preStopSleepSeconds=0")
    assert "lifecycle" not in pod["containers"][0]


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
def test_a_recreate_backend_sweeps_at_once_and_keeps_the_frontend_rolling():
    # SQLite on a shared volume: the old backend stops before the new one starts, so no run of the old
    # pod can still be going when the new one sweeps — and the stateless frontend needn't stop first.
    args = (
        "--set",
        "mode=split",
        "--set",
        "config.dbEngine=postgres",
        "--set",
        "postgres.cluster.enabled=true",
        "--set",
        "split.backend.strategy.type=Recreate",
    )
    out = subprocess.run(["helm", "template", "t", str(CHART), *args], check=True, capture_output=True, text=True).stdout
    deployments = {d["metadata"]["name"]: d for d in yaml.safe_load_all(out) if d and d.get("kind") == "Deployment"}
    assert deployments["t-marvin-backend"]["spec"]["strategy"] == {"type": "Recreate"}
    assert deployments["t-marvin-frontend"]["spec"]["strategy"]["type"] == "RollingUpdate"
    env = {e["name"]: e.get("value") for e in deployments["t-marvin-backend"]["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["AI_INTERRUPTED_RUN_SWEEP_DELAY_SECONDS"] == "0"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
@pytest.mark.parametrize("mode", ["combined", "split"])
def test_a_sqlite_release_always_recreates_its_backend(mode):
    # One writer to one file: whatever strategy is asked for, the old pod stops before the new one starts.
    out = subprocess.run(
        ["helm", "template", "t", str(CHART), "--set", f"mode={mode}", "--set", "strategy.type=RollingUpdate"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    deployments = {d["metadata"]["name"]: d for d in yaml.safe_load_all(out) if d and d.get("kind") == "Deployment"}
    backend = deployments["t-marvin-backend" if mode == "split" else "t-marvin"]
    assert backend["spec"]["strategy"] == {"type": "Recreate"}
    env = {e["name"]: e.get("value") for e in backend["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["AI_INTERRUPTED_RUN_SWEEP_DELAY_SECONDS"] == "0"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--set", "replicaCount=2"], "one API replica"),
        (["--set", "mode=split", "--set", "split.backend.replicaCount=2"], "one API replica"),
        (["--set", "persistence.enabled=false"], "persistence.enabled"),
        (["--set", "config.dbEngine=mysql"], "sqlite or postgres"),
    ],
)
def test_the_chart_refuses_a_sqlite_release_that_would_corrupt_or_lose_its_database(args, message):
    done = subprocess.run(["helm", "template", "t", str(CHART), *args], capture_output=True, text=True)
    assert done.returncode != 0 and message in done.stderr
