#!/usr/bin/env bash
# Lint the chart and render it with every values file, then check the database engine each one renders.
# Run by .github/workflows/helm.yml (lint job) and `task helm:lint`. Rendered output lands in ${HELM_OUT:-/tmp}/marvin-templates*.
#
# The chart's default is SQLite (a plain install needs no operator); every environment's values file pins Postgres and
# a CloudNativePG Cluster. A values file that loses its pin would deploy that environment onto an empty SQLite file, so
# each one is rendered and checked: engine in the ConfigMap, and the Cluster.
# `--api-versions route.openshift.io/v1` makes the OpenShift Route render: it is capability-gated, so it silently
# vanishes from a plain `helm template`, leaving it untested.
set -euo pipefail
cd "$(dirname "$0")/.."
out="${HELM_OUT:-/tmp}"
chart=marvin-chart/

helm lint "$chart" --strict

helm template marvin "$chart" --output-dir "$out/marvin-templates" >/dev/null
helm template marvin "$chart" --values marvin-chart/values-production.yaml --set image.tag=latest \
  --api-versions route.openshift.io/v1 --output-dir "$out/marvin-templates-prod" >/dev/null
helm template marvin "$chart" --namespace marvin-dev --values marvin-chart/values-dev.yaml \
  --api-versions route.openshift.io/v1 --output-dir "$out/marvin-templates-dev" >/dev/null
helm template marvin "$chart" --values marvin-chart/values-iwobble.yaml \
  --api-versions route.openshift.io/v1 --output-dir "$out/marvin-templates-iwobble" >/dev/null

render() { helm template marvin "$chart" --api-versions route.openshift.io/v1 "$@"; }

render > "$out/engine-default.yaml"
grep -q 'dbEngine: "sqlite"' "$out/engine-default.yaml"
if grep -q 'apiVersion: postgresql.cnpg.io' "$out/engine-default.yaml"; then
  echo "default values must not render a CloudNativePG Cluster"; exit 1
fi
echo "default: sqlite, no Cluster"

for env in iwobble dev production k8s; do
  render --values "marvin-chart/values-$env.yaml" --set image.tag=latest > "$out/engine-$env.yaml"
  grep -q 'dbEngine: "postgres"' "$out/engine-$env.yaml" \
    || { echo "values-$env.yaml does not render dbEngine: \"postgres\""; exit 1; }
  grep -q 'apiVersion: postgresql.cnpg.io' "$out/engine-$env.yaml" \
    || { echo "values-$env.yaml does not render a CloudNativePG Cluster"; exit 1; }
  echo "$env: postgres + CloudNativePG Cluster"
done
