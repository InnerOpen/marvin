// "What it installed" on an integration's card: the footprint API's answer turned into the sections the card shows.
// Each kind's heading links to its page filtered to this integration (`?from=integration:<id>`, the kit's From filter —
// see organizedList.urlFilters). Pure, so it is tested without a DOM.

export interface FootprintItem {
  id: string;
  name: string;
  enabled?: boolean | null;
}

export interface FootprintFieldChange {
  entryTypeSlug: string;
  entryTypeName: string;
  label: string;
}

export interface IntegrationFootprint {
  integrationId: string;
  workflows: FootprintItem[];
  incomingWebhooks: FootprintItem[];
  outgoingWebhooks: FootprintItem[];
  scheduledTasks: FootprintItem[];
  collections: FootprintItem[];
  /** Playbooks the integration shipped and the workspace added; `enabled` means published. */
  playbooks: FootprintItem[];
  fieldChanges: FootprintFieldChange[];
  total: number;
}

export interface FootprintSection {
  kind: keyof Pick<
    IntegrationFootprint,
    "workflows" | "incomingWebhooks" | "outgoingWebhooks" | "scheduledTasks" | "collections" | "playbooks"
  >;
  /** "3 workflows" */
  heading: string;
  href: string;
  items: FootprintItem[];
}

// [kind, singular, plural, page]. Collections have no From filter (they are not on the list kit), so they link to the plain page.
const KINDS = [
  ["workflows", "workflow", "workflows", "/automation/workflows"],
  ["incomingWebhooks", "incoming webhook", "incoming webhooks", "/automation/incoming-webhooks"],
  ["outgoingWebhooks", "outgoing webhook", "outgoing webhooks", "/automation/webhooks"],
  ["scheduledTasks", "scheduled task", "scheduled tasks", "/workspace/scheduled-tasks"],
  ["collections", "collection", "collections", "/workspace/collections"],
  ["playbooks", "Playbook", "Playbooks", "/workspace/settings/ai-playbooks"],
] as const;

export function fromHref(page: string, integrationId: string): string {
  return `${page}?from=${encodeURIComponent(`integration:${integrationId}`)}`;
}

/** The kinds the integration installed something of, in a fixed order; kinds with nothing are left out. */
export function footprintSections(footprint: IntegrationFootprint): FootprintSection[] {
  return KINDS.flatMap(([kind, one, many, page]) => {
    const items = footprint[kind] ?? [];
    if (items.length === 0) return [];
    return [
      {
        kind,
        heading: `${items.length} ${items.length === 1 ? one : many}`,
        href: kind === "collections" ? page : fromHref(page, footprint.integrationId),
        items,
      },
    ];
  });
}

/** Nothing installed and nothing changed: the card says so rather than showing an empty box. */
export function footprintIsEmpty(footprint: IntegrationFootprint): boolean {
  return footprint.total === 0 && footprint.fieldChanges.length === 0;
}

/** "5 things installed" / "Nothing installed yet" for the section's summary. */
export function footprintSummary(footprint: IntegrationFootprint): string {
  if (footprintIsEmpty(footprint)) return "nothing yet";
  const parts = [];
  if (footprint.total > 0) parts.push(`${footprint.total} ${footprint.total === 1 ? "item" : "items"}`);
  if (footprint.fieldChanges.length > 0)
    parts.push(
      footprint.fieldChanges.length === 1 ? "1 type changed" : `${footprint.fieldChanges.length} types changed`,
    );
  return parts.join(", ");
}
