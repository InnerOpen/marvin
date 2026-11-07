/**
 * Packages: a named, versioned bundle of blueprints (entry types, workflows, collections...) a workspace installs, uploads, builds from
 * its own content, downloads and removes. Owners and admins only (the server refuses everyone else), so callers that show something
 * for everyone (the Workflows page's section titles) catch the refusal and carry on.
 *
 * Installing creates what is missing and never overwrites; workflows and the like start switched off, and `enablePackage` is the
 * separate step that turns a package's workflows on. Browser calls go through the same-origin proxy (fetchApi with no token); SSR
 * passes the cookie token.
 */

import { fetchApi } from "./client";

export type PackageItemStatus = "create" | "created" | "exists" | "blocked";

export interface PackageItem {
  slug: string;
  kind: string;
  name: string;
  status: PackageItemStatus;
  detail: string;
  /** A workflow: when it runs and what its steps are, in a line. */
  summary: string;
}

export interface PackageResult {
  package: string;
  name: string;
  items: PackageItem[];
  created: number;
  existing: number;
  blocked: number;
}

export interface PackageInfo {
  slug: string;
  name: string;
  description: string;
  version: string;
  entryTypes: string[];
  wizards?: string[];
  workflows: number;
  workflowsOn: number;
  collections: number;
  scheduledTasks: number;
  incomingWebhooks: number;
}

/** A package file's JSON (see `PackageManifest` on the server); the browser passes it on as it was read. */
export type PackageManifest = Record<string, unknown> & { slug?: string; name?: string; blueprints?: unknown[] };

export interface ExportRequest {
  slug: string;
  name: string;
  description?: string;
  version?: string;
  workflows: string[];
  entryTypes: string[];
  collections: string[];
  /** Also group the chosen workflows and collections into the package here (nothing is recreated). */
  adopt: boolean;
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export const listPackages = (authToken?: string) => fetchApi<PackageInfo[]>("/api/groups/packages", {}, authToken);

/** What installing would do, per blueprint. Changes nothing. */
export const previewPackage = (manifest: PackageManifest) =>
  fetchApi<PackageResult>("/api/groups/packages/preview", { method: "POST", body: JSON.stringify(manifest), headers: JSON_HEADERS });

export const installPackage = (manifest: PackageManifest) =>
  fetchApi<PackageResult>("/api/groups/packages/install", { method: "POST", body: JSON.stringify(manifest), headers: JSON_HEADERS });

/** Bundle chosen content of this workspace; the response is the package file's JSON. */
export const exportPackage = (request: ExportRequest) =>
  fetchApi<PackageManifest>("/api/groups/packages/export", { method: "POST", body: JSON.stringify(request), headers: JSON_HEADERS });

export const enablePackage = (slug: string) =>
  fetchApi<{ switchedOn: number; alreadyOn: number }>(`/api/groups/packages/${encodeURIComponent(slug)}/enable`, { method: "POST" });

/** Ungroups it; nothing it created is deleted. */
export const removePackage = (slug: string) =>
  fetchApi<{ ungrouped: number }>(`/api/groups/packages/${encodeURIComponent(slug)}`, { method: "DELETE" });

export const downloadUrl = (slug: string) => `/api/groups/packages/${encodeURIComponent(slug)}/download`;

/** The package as its file (what a download saves), read through the same call the browser uses for everything else. */
export const getPackageFile = (slug: string) => fetchApi<PackageManifest>(downloadUrl(slug));
