// An integration's Playbook on its card (Settings › Integrations › Content › Optional): what the row says once it is added, and
// the wording of the Update confirmation. Pure, so `npm test` covers it (playbookBlueprint.test.mjs). Backend:
// services/blueprints/playbook_apply.py; the card is pages/workspace/settings/integrations.astro.

import type { Blueprint } from "./api/blueprints.ts";
import { editorPath } from "./playbooks.ts";

export interface PlaybookCardNote {
  text: string;
  /** The Playbooks page entry to open, when there is one. */
  href: string | null;
}

/** What an added Playbook's row says: a new one is a draft to review and publish; the status otherwise. Null for another kind of row. */
export function playbookCardNote(b: Pick<Blueprint, "kind" | "applied" | "installedId" | "installedStatus">): PlaybookCardNote | null {
  if (b.kind !== "playbook" || !b.applied) return null;
  const href = b.installedId ? editorPath(b.installedId) : null;
  if (b.installedStatus === "published") return { text: "Published", href };
  if (b.installedStatus === "archived") return { text: "Archived", href };
  return { text: "Draft: review and publish", href };
}

/** The words under the Update confirmation. A Playbook keeps its status, so a published one changes for agents at once. */
export function updateConfirmText(kind: string, name: string): string {
  if (kind === "playbook") {
    return (
      `"${name}" was changed in this workspace. Updating replaces those changes with the integration's current version. ` +
      "The old version stays in its history. If it is published, agents use the new version at once."
    );
  }
  return (
    `"${name}" was changed in this workspace. Updating replaces those changes with the integration's ` +
    "current version. Whether it's switched on stays as it is."
  );
}
