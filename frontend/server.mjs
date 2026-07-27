// Trust-proxy wrapper around the Astro SSR server.
//
// The frontend is @astrojs/node in standalone mode. Behind a TLS-terminating reverse proxy (an
// OpenShift edge route, an ingress, etc.) the pod receives plain HTTP, and Astro's request builder
// reads the scheme from the socket — so it reconstructs the request URL as http://… . That makes
// Astro's built-in CSRF protection (`security.checkOrigin`, on by default) reject same-site form
// POSTs: the browser sends `Origin: https://host` while Astro computed `http://host`, and the two
// don't match ("Cross-site POST form submissions are forbidden").
//
// We keep checkOrigin ON and fix the mismatch at the edge of our own process: when the proxy tells
// us the original request was HTTPS (X-Forwarded-Proto), mark the socket encrypted before Astro
// builds the Request, so it reconstructs the correct https origin.
//
// The standalone entry would auto-start its own server on import, which ignores this preprocessing;
// we disable that with ASTRO_NODE_AUTOSTART=disabled (set by the start scripts) and drive its
// exported handler — which still serves both static assets and SSR — from our own http server.
import http from "node:http";

import { handler } from "./dist/server/entry.mjs";

const host = process.env.HOST ?? "0.0.0.0";
const port = Number.parseInt(process.env.PORT ?? process.env.FRONTEND_PORT ?? "4322", 10);

// Only https is meaningful here: an http forwarded-proto is already the default, and anything else
// we leave untouched so a misconfigured header can't downgrade a genuinely encrypted socket.
function trustForwardedProto(req) {
  if (req.headers["x-forwarded-proto"] !== "https") return;
  if (!req.socket || req.socket.encrypted) return;
  try {
    Object.defineProperty(req.socket, "encrypted", { value: true, configurable: true });
  } catch {
    // If the property can't be redefined on this socket, fall through — behavior is unchanged.
  }
}

const server = http.createServer((req, res) => {
  trustForwardedProto(req);
  handler(req, res);
});

server.listen(port, host, () => {
  process.stdout.write(`frontend listening on http://${host}:${port} (trust-proxy: x-forwarded-proto)\n`);
});
