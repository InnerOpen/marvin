"""Every site-wide plugin is baked into this image and loads: run inside the image by CI (docker.yml).

PLUGINS names the distributions (pyproject.toml's `plugins` group). For each: installed, it declares a Marvin
plugin entry point, and every such entry point imports — so a plugin that is missing or broken fails the build
here instead of being skipped with a log line when a pod starts.
"""

import importlib.metadata as metadata
import os
import sys

GROUPS = ("marvin.integrations", "marvin.storage_providers", "marvin.ai_providers")

problems = []
for name in os.environ["PLUGINS"].split():
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        problems.append(f"{name}: not installed")
        continue
    points = [e for e in dist.entry_points if e.group in GROUPS]
    if not points:
        problems.append(f"{name}: declares no Marvin plugin entry point")
    for point in points:
        try:
            point.load()
        except Exception as e:  # noqa: BLE001 - report every broken plugin, not just the first
            problems.append(f"{name}: {point.group} {point.name} failed to load: {e!r}")
    print(f"{name} {dist.version}: {', '.join(f'{p.group.rsplit(".", 1)[-1]}:{p.name}' for p in points)}")

if problems:
    print("\n".join(problems), file=sys.stderr)
    sys.exit(1)
print(f"✅ {len(os.environ['PLUGINS'].split())} plugins baked in and loading")
