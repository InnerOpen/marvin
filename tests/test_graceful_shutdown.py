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
    out = subprocess.run(["helm", "template", "t", str(CHART), *args], check=True, capture_output=True, text=True).stdout
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
