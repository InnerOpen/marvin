#!/usr/bin/env bash
# Entrypoint for the standalone frontend image (split mode). Runs only the Astro SSR server.
#
# Unlike docker/start.sh (the combined image), this container has no Python, so it cannot ask
# AppSettings for the port — it reads FRONTEND_PORT directly, defaulting to 4322. The backend URL
# is resolved at request time from the environment (PUBLIC_MARVIN_API_URL / MARVIN_API_URL) and
# injected into each page, so one image serves any deployment. See frontend/src/lib/api/config.ts.
set -uo pipefail

port="${FRONTEND_PORT:-4322}"
echo "start-frontend.sh: frontend listening on ${port}"

# The @astrojs/node standalone server reads HOST and PORT from the environment. Launch through the
# trust-proxy wrapper (server.mjs) so a TLS-terminating route's X-Forwarded-Proto is honored and
# Astro's checkOrigin works; ASTRO_NODE_AUTOSTART=disabled stops the standalone entry from also
# starting its own server on import.
export HOST="${HOST:-0.0.0.0}"
export PORT="$port"
export ASTRO_NODE_AUTOSTART=disabled
exec node /app/frontend/server.mjs
