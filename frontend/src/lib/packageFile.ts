// Pure helpers for packages (no network, so `npm test` covers them): reading a chosen file, naming, describing a preview.
// The calls themselves are in api/packages.ts.

import type { PackageManifest, PackageResult } from "./api/packages.ts";

/** "3 will be created, 1 already here, 1 blocked" for a preview, or "created" for the result of an install. */
export function describeResult(result: Pick<PackageResult, "created" | "existing" | "blocked">, preview: boolean): string {
  const parts = [
    result.created ? `${result.created} ${preview ? "will be created" : "created"}` : "",
    result.existing ? `${result.existing} already here` : "",
    result.blocked ? `${result.blocked} blocked` : "",
  ].filter(Boolean);
  return parts.length ? parts.join(", ") : "nothing to do";
}

/** A package file's name for the download: "story-kit" -> "story-kit.marvin-package.json". */
export const fileNameFor = (slug: string) => `${slug}.marvin-package.json`;

/** The slug a package gets from its name when the person does not choose one: "Story kit!" -> "story-kit". */
export function slugFor(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

/** Reads a chosen file as a package manifest, or says why it cannot be one. */
export function parseManifestText(text: string): PackageManifest {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error("This is not a package file: it is not valid JSON.");
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("This is not a package file: expected a JSON object.");
  const manifest = parsed as PackageManifest;
  if (!Array.isArray(manifest.blueprints) || !manifest.slug || !manifest.name) {
    throw new Error("This does not look like a package: it needs a slug, a name and a list of blueprints.");
  }
  return manifest;
}
