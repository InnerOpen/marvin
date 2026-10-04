// Whether the Ask bubble shows at all, from the workspace's AI settings (GET /api/groups/ai-settings).

/** Minimal shape of the AI settings the bubble reads. */
export interface BubbleGateSettings {
  enabled?: boolean | null;
  invocationSources?: Record<string, boolean | null | undefined> | null;
}

/**
 * The bubble shows only while AI is on for the workspace and the "Ask {assistant}" invocation source
 * (`agent`) isn't switched off. A source is allowed unless the policy explicitly sets it false — the
 * same rule the backend gate and the settings toggles use.
 */
export function bubbleAllowed(settings: BubbleGateSettings | null | undefined): boolean {
  if (!settings || settings.enabled === false) return false;
  return settings.invocationSources?.agent !== false;
}
