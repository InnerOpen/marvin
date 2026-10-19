#!/usr/bin/env bash
# How many pytest-xdist workers this machine should run: the container's CPU quota (cgroup v2 cpu.max), at least 2.
# `-n auto` counts the node's cores, which in a CPU-limited pod (the self-hosted runner) starts far more workers than it
# has CPU for. Without a quota — a VM, a laptop — it prints "auto". Used by .github/workflows/test.yml.
quota=/sys/fs/cgroup/cpu.max
if [[ -r $quota ]]; then
  awk '{ if ($1 == "max") print "auto"; else { n = int($1 / $2); print (n < 2 ? 2 : n) } }' "$quota"
else
  echo auto
fi
