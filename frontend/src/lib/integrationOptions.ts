/**
 * The `x-marvin-options` hint on an integration action input: its valid values come from a read
 * action on the same provider, which core runs through the connection
 * (`POST /api/groups/integrations/{id}/options`). Pure helpers here (unit-tested); the picker UI is
 * integrationOptionPicker.ts.
 *
 *   "path": {"type": "string", "x-marvin-options": {"action": "list_workflows", "value": "path", "label": "name"}}
 */

export interface OptionsHint {
  action: string;
  value: string;
  label?: string;
  args?: Record<string, unknown>;
}

export interface InputOption {
  value: string | number | boolean;
  label: string;
}

export const OPTIONS_HINT = "x-marvin-options";

/** The input's hint, or null when it has none (or a malformed one — the input stays free text). */
export function optionsHint(prop: unknown): OptionsHint | null {
  if (!prop || typeof prop !== "object") return null;
  const hint = (prop as Record<string, unknown>)[OPTIONS_HINT];
  if (!hint || typeof hint !== "object") return null;
  const { action, value, label } = hint as Record<string, unknown>;
  if (typeof action !== "string" || !action || typeof value !== "string" || !value) return null;
  if (label !== undefined && typeof label !== "string") return null;
  return hint as OptionsHint;
}

/** The keys of an action's inputs that carry a hint, in schema order. */
export function hintedInputs(schema: unknown): string[] {
  const props = (schema as { properties?: Record<string, unknown> } | null)?.properties ?? {};
  return Object.keys(props).filter((k) => optionsHint(props[k]) !== null);
}

/** Options whose label or value contains `query` (case-insensitive). */
export function filterOptions(options: InputOption[], query: string): InputOption[] {
  const q = query.trim().toLowerCase();
  if (!q) return options;
  return options.filter((o) => o.label.toLowerCase().includes(q) || String(o.value).toLowerCase().includes(q));
}

/** The option whose value matches `current` (compared as text, since inputs hold strings). */
export function findOption(options: InputOption[], current: unknown): InputOption | undefined {
  if (current === undefined || current === null || current === "") return undefined;
  return options.find((o) => String(o.value) === String(current));
}

/**
 * Set one key in a JSON-object args text, keeping everything else. Empty value removes the key.
 * Returns null when the text isn't a JSON object (the caller leaves it for the person to fix).
 */
export function setArg(text: string, key: string, value: unknown): string | null {
  let args: Record<string, unknown> = {};
  if (text.trim()) {
    try {
      const parsed = JSON.parse(text);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
      args = parsed;
    } catch {
      return null;
    }
  }
  if (value === undefined || value === null || value === "") delete args[key];
  else args[key] = value;
  return Object.keys(args).length ? JSON.stringify(args, null, 2) : "";
}

/** One key from a JSON-object args text, or undefined (missing, or the text doesn't parse). */
export function getArg(text: string, key: string): unknown {
  try {
    const parsed = JSON.parse(text || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed[key] : undefined;
  } catch {
    return undefined;
  }
}
