#!/usr/bin/env bash
# Run the backend API and the server-rendered frontend side by side in one container.
#
# The frontend is Astro with output: "server" (@astrojs/node standalone), so it needs a live Node
# process — it can't be served as static files from the API. We supervise both here: if either one
# exits, the whole container comes down with that status, so an orchestrator restarts a half-dead
# app instead of leaving it limping.
set -uo pipefail

shutdown() {
    trap - TERM INT
    kill -TERM "${backend_pid:-}" "${frontend_pid:-}" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap shutdown TERM INT

# Ask the application where the frontend should listen instead of hardcoding a port here. This
# resolves FRONTEND_PORT, falling back to the port in FRONTEND_URL, and it reads .env the same way
# the API does — so the setting that advertises the frontend is also the one it binds to. The
# previous literal default (4321) disagreed with the advertised default (4322), and no value of
# either setting could move it.
resolved_port="$(python -c 'from marvin.core.config import get_app_settings; print(get_app_settings().FRONTEND_PORT)' 2>/dev/null)"
case "$resolved_port" in
    ''|*[!0-9]*)
        # Settings could not be loaded (bad .env, import failure). Fall back rather than refuse to
        # boot the frontend, and say so — a silent default is how the two drifted apart before.
        echo "start.sh: could not resolve FRONTEND_PORT from settings, falling back to 4322" >&2
        resolved_port=4322
        ;;
esac

# Backend API (uvicorn via the console script; reads API_PORT/HOST from the environment).
marvin-server &
backend_pid=$!

# Frontend SSR server. Launched through the trust-proxy wrapper (server.mjs) so a TLS-terminating
# route's X-Forwarded-Proto is honored and Astro's checkOrigin works; ASTRO_NODE_AUTOSTART=disabled
# stops the standalone entry from also starting its own server on import. Reads HOST/PORT at runtime;
# bind all interfaces on its own port so it doesn't collide with the API.
echo "start.sh: frontend listening on ${resolved_port}"
HOST=0.0.0.0 PORT="$resolved_port" ASTRO_NODE_AUTOSTART=disabled node /app/frontend/server.mjs &
frontend_pid=$!

# Return as soon as either process exits, propagating its status.
wait -n
status=$?
shutdown
exit "$status"
