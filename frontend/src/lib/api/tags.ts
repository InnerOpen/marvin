/**
 * Tags API client - SDK wrapper (platform.tags)
 *
 * `createTag` is find-or-create by slug server-side — call it to resolve a freshly typed
 * tag name to a stable id (the "create-on-type" primitive the entry editor uses on save).
 */

import type { PlatformTag, PlatformTagCreate } from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";

export type TagRead = PlatformTag;
export type TagCreate = PlatformTagCreate;

/** List all tags in the current workspace (each carries an entryCount). */
export async function listTags(authToken?: string): Promise<TagRead[]> {
  return createSdkClient(authToken).tags.list();
}

/** Find-or-create a tag by slug. Returns the existing tag if the name already resolves to one. */
export async function createTag(data: TagCreate, authToken?: string): Promise<TagRead> {
  return createSdkClient(authToken).tags.create(data);
}
