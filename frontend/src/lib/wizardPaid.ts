/**
 * Paid actions of a guided setup. A run step, a gallery's generate, a card action or an add button may say `paid`: it sends something
 * to an outside service that charges for it. The page then says so before anything goes, shows the text that will be sent (the fields
 * named in `sends`, as they are now), warns when one that matters (`needs`) is empty, and keeps the button in a section of its own.
 * Pure, so it runs under `node --test`: the page fetches.
 */

export interface Paid {
  /** The outside service, by name ("ElevenLabs"); "" when the package does not say. */
  service: string;
  /** What it costs, in the package's words; "" when it does not say. */
  cost: string;
  /** The chosen entry whose fields are sent (a run step, a generate): a context key. A card action sends its card's, an add button its form's. */
  entry?: string;
  /** The fields that are sent. */
  sends: string[];
  /** Those of them that should not be empty. */
  needs: string[];
}

/** What was sent, to show: each field that holds something under its label, and the labels of the needed ones that are empty. */
export interface Sent {
  lines: { key: string; label: string; value: string }[];
  missing: string[];
}

const keys = (value: unknown): string[] => (Array.isArray(value) ? value.filter((k): k is string => typeof k === "string" && !!k) : []);
const words = (value: unknown): string => (typeof value === "string" ? value.trim() : "");

/** A `paid` as the definition gives it (`true`, or `{service?, cost?, entry?, sends?, needs?}`), read; null when the action is not paid. */
export function paidOf(spec: unknown): Paid | null {
  if (spec === true) return { service: "", cost: "", sends: [], needs: [] };
  if (!spec || typeof spec !== "object" || Array.isArray(spec)) return null;
  const given = spec as Record<string, unknown>;
  const sends = keys(given.sends);
  return {
    service: words(given.service),
    cost: words(given.cost),
    ...(words(given.entry) ? { entry: words(given.entry) } : {}),
    sends,
    needs: keys(given.needs).filter((k) => sends.includes(k)),
  };
}

/** "Words", "Words and Direction", "Words, Direction and Voice". */
export function namedList(names: string[]): string {
  return names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : (names[0] ?? "");
}

/** The notice: "This sends your request to a paid outside service (ElevenLabs). About 2 cents a line." `what` says what goes. */
export function paidLine(paid: Paid, what = "your request"): string {
  return `This sends ${what} to a paid outside service${paid.service ? ` (${paid.service})` : ""}.${paid.cost ? ` ${paid.cost}` : ""}`;
}

/** A field's name as a sentence says it: its label without the explanation in brackets, else its key. */
function labelOf(fields: { key?: string; label?: string }[], key: string): string {
  return (fields.find((f) => f.key === key)?.label ?? "").replace(/\s*\(.*\)\s*$/, "").trim() || key;
}

const textOf = (raw: unknown): string => (typeof raw === "string" ? raw.trim() : typeof raw === "number" ? String(raw) : "");

/** What will be sent, from the entry's data as it is now: the `sends` fields that hold text, and which `needs` are empty. */
export function paidSent(paid: Paid, data: Record<string, unknown> | null | undefined, fields: { key?: string; label?: string }[] = []): Sent {
  return {
    lines: paid.sends.flatMap((key) => (textOf(data?.[key]) ? [{ key, label: labelOf(fields, key), value: textOf(data?.[key]) }] : [])),
    missing: paid.needs.filter((key) => !textOf(data?.[key])).map((key) => labelOf(fields, key)),
  };
}

/** The labels of an add form's `sends` fields ("Words and Direction"), for "This sends the … above". */
export function paidFields(paid: Paid, fields: { key?: string; label?: string }[] = []): string {
  return namedList(paid.sends.map((key) => labelOf(fields, key)));
}

/** "“Direction” is empty: it is sent without it."; null when nothing needed is missing. */
export function paidWarning(missing: string[]): string | null {
  if (!missing.length) return null;
  const named = namedList(missing.map((m) => `“${m}”`));
  return missing.length === 1 ? `${named} is empty: it is sent without it.` : `${named} are empty: it is sent without them.`;
}

const MAX_CONFIRM_VALUE = 400;

/** What a paid button on a card asks before it sends: the notice, the text that goes (a long one cut short), what is missing, and the
 *  button's own words as the question. */
export function paidConfirm(button: string, paid: Paid, sent: Sent): string {
  const cut = (value: string) => (value.length > MAX_CONFIRM_VALUE ? `${value.slice(0, MAX_CONFIRM_VALUE - 1).trimEnd()}…` : value);
  const parts = [paidLine(paid), sent.lines.map((l) => `${l.label}: ${cut(l.value)}`).join("\n"), paidWarning(sent.missing) ?? "", `${button.trim()}?`];
  return parts.filter(Boolean).join("\n\n");
}

/** The line above a gallery's cards when some of their buttons are paid: "“Make this one” and “Make it again” send to a paid outside
 *  service (ElevenLabs), and each asks first." */
export function paidCardsLine(actions: { label: string; paid: Paid }[]): string {
  const one = actions.length === 1;
  const services = [...new Set(actions.map((a) => a.paid.service).filter(Boolean))];
  const to = `a paid outside service${services.length ? ` (${services.join(", ")})` : ""}`;
  return `${namedList(actions.map((a) => `“${a.label}”`))} ${one ? "sends" : "send"} to ${to}, and ${one ? "asks" : "each asks"} first.`;
}
