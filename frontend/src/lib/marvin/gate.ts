// Whether the Ask surfaces show at all, from the workspace's AI settings (GET /api/groups/ai-settings).

type SourcesPolicy = Record<string, boolean | null | undefined> | null | undefined;

/** Minimal shape of the AI settings the Ask surfaces read. */
export interface BubbleGateSettings {
  enabled?: boolean | null;
  invocationSources?: SourcesPolicy;
}

/** The two Ask surfaces, each with its own invocation-source toggle. */
export const ASK_SURFACES = ["bubble", "ask_page"] as const;

/**
 * Whether the invocation_sources policy leaves `key` on — the backend gate's rule (`source_allowed`):
 * a source is on unless explicitly false, and an Ask surface is also off while the legacy `agent` key
 * (the single "Ask" toggle before the split) is false.
 */
export function sourceAllowed(policy: SourcesPolicy, key: string): boolean {
  if (policy?.[key] === false) return false;
  return !((ASK_SURFACES as readonly string[]).includes(key) && policy?.agent === false);
}

function surfaceAllowed(settings: BubbleGateSettings | null | undefined, key: string): boolean {
  if (!settings || settings.enabled === false) return false;
  return sourceAllowed(settings.invocationSources, key);
}

/** The bubble shows only while AI is on for the workspace and the `bubble` source isn't switched off. */
export function bubbleAllowed(settings: BubbleGateSettings | null | undefined): boolean {
  return surfaceAllowed(settings, "bubble");
}

/** The Ask page (and its sidebar link) works only while AI is on and the `ask_page` source isn't off. */
export function askPageAllowed(settings: BubbleGateSettings | null | undefined): boolean {
  return surfaceAllowed(settings, "ask_page");
}
