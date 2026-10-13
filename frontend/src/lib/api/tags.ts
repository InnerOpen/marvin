/**
 * Tags API client - SDK wrapper (platform.tags)
 *
 * `createTag` is find-or-create by slug server-side — call it to resolve a freshly typed
 * tag name to a stable id (the "create-on-type" primitive the entry editor uses on save).
 */

import type { PlatformTag, PlatformTagCreate, PlatformTagUpdate } from "@inneropen/marvin-sdk/platform";
import { createSdkClient } from "../sdk";

export type TagRead = PlatformTag;
export type TagCreate = PlatformTagCreate;
export type TagUpdate = PlatformTagUpdate;

/** List all tags in the current workspace (each carries an entryCount). */
export async function listTags(authToken?: string): Promise<TagRead[]> {
  return createSdkClient(authToken).tags.list();
}

/** Find-or-create a tag by slug. Returns the existing tag if the name already resolves to one. */
export async function createTag(data: TagCreate, authToken?: string): Promise<TagRead> {
  return createSdkClient(authToken).tags.create(data);
}

/** Rename/recolor a tag (slug is stable). */
export async function updateTag(id: string, data: TagUpdate, authToken?: string): Promise<TagRead> {
  return createSdkClient(authToken).tags.update(id, data);
}

/** Delete a tag (unlabels every entry carrying it). */
export async function deleteTag(id: string, authToken?: string): Promise<void> {
  return createSdkClient(authToken).tags.delete(id);
}
