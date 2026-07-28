/**
 * Lightweight liveness/readiness endpoint for the SSR server.
 *
 * Returns 200 without rendering a page or calling the backend — so infrastructure probes don't
 * SSR-render /login (and fetch /api/app/about/login-info) on every check. Point the frontend's
 * k8s probes and the Docker HEALTHCHECK here instead of /login.
 */
import type { APIRoute } from "astro";

export const GET: APIRoute = () =>
  new Response("ok", { status: 200, headers: { "content-type": "text/plain; charset=utf-8" } });
