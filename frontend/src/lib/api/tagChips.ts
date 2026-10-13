/**
 * Client helper for the TagChips component.
 *
 * The chip UI writes a JSON array of {name, id?} into a hidden input; on save the page reads it
 * and calls `resolveTagIds` to turn it into the tag_ids array the entity update expects. A chip
 * with an id is an existing tag; a bare name is create-on-type, resolved via find-or-create
 * (POST /tags). De-duplicates while preserving order.
 */

import { createSdkClient } from "../sdk";

export interface TagChip {
  name: string;
  id?: string;
}

/** Read the hidden payload input and resolve it to a de-duplicated tag_ids array. */
export async function resolveTagIds(payloadEl: HTMLInputElement | null, authToken?: string): Promise<string[]> {
  if (!payloadEl) return [];
  let chips: TagChip[] = [];
  try {
    chips = JSON.parse(payloadEl.value || "[]");
  } catch {
    chips = [];
  }
  const sdk = createSdkClient(authToken);
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const chip of chips) {
    let id = chip.id;
    if (!id && chip.name?.trim()) {
      const tag = await sdk.tags.create({ name: chip.name.trim() });
      id = tag.id;
    }
    if (id && !seen.has(id)) {
      seen.add(id);
      ids.push(id);
    }
  }
  return ids;
}
