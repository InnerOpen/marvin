/// <reference path="../.astro/types.d.ts" />
/// <reference types="astro/client" />

interface ImportMetaEnv {
  readonly MARVIN_API_URL?: string;
  readonly MARVIN_GROUP_SLUG?: string;
  readonly MARVIN_SITE_CLIENT_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare namespace App {
  interface Locals {
    /**
     * This request's shared API reads (lib/requestCache.ts): the signed-in user, their workspaces, the current one and
     * the layout's lists, each read once however many components ask. Set by the middleware on GET and HEAD requests
     * only — a POST writes and then renders, so it reads fresh.
     */
    apiCache?: import("./lib/requestCache").RequestCache;
  }
}
