// "How errors are handled" — a provider's declared error policy as table rows, with the connection's
// review/alert adjustments applied. Pure, so it's tested with plain `node --test`
// (see integrationPolicy.test.mjs).

/** One code's handling, as the SDK's Handle.to_dict() serializes it. */
export interface PolicyHandle {
  review: boolean;
  notify: boolean;
  succeed: boolean;
  retry: { backoff: number[]; max_attempts: number; on_recovery: boolean } | null;
  then: PolicyHandle | null;
  summary: string;
}

/** The provider's policies: provider-wide, and per action (an action's own entry wins for that action). */
export interface ErrorPolicyInfo {
  provider?: Record<string, PolicyHandle>;
  actions?: Record<string, Record<string, PolicyHandle>>;
}

/** An admin's per-connection adjustments: code (or "*") → the immediate review / notify flags. */
export type ErrorOverrides = Record<string, { review?: boolean; notify?: boolean }>;

type Flags = { review: boolean; notify: boolean };

export interface PolicyRow {
  code: string;
  /** "*" reads as "Any other error". */
  label: string;
  /** Where the code is declared and what happens there, provider-wide first. */
  declared: { scope: string; summary: string }[];
  defaults: Flags;
  effective: Flags;
  overridden: boolean;
}

export const FALLBACK = "*";

/**
 * One row per declared code (provider-wide codes first, then codes only an action names, "*" last).
 * A code's default flags are its provider-wide handling, else the first action's that names it.
 */
export function policyRows(
  policy: ErrorPolicyInfo | null | undefined,
  actionLabels: Record<string, string> = {},
  overrides: ErrorOverrides | null | undefined = {},
): PolicyRow[] {
  if (!policy) return [];
  const rows = new Map<string, PolicyRow>();
  const add = (code: string, scope: string, handle: PolicyHandle) => {
    const row = rows.get(code);
    if (row) {
      row.declared.push({ scope, summary: handle.summary });
      return;
    }
    const defaults = { review: Boolean(handle.review), notify: Boolean(handle.notify) };
    const own = overrides?.[code] ?? {};
    const effective = { review: own.review ?? defaults.review, notify: own.notify ?? defaults.notify };
    rows.set(code, {
      code,
      label: code === FALLBACK ? "Any other error" : code,
      declared: [{ scope, summary: handle.summary }],
      defaults,
      effective,
      overridden: effective.review !== defaults.review || effective.notify !== defaults.notify,
    });
  };
  for (const [code, handle] of Object.entries(policy.provider ?? {})) add(code, "All actions", handle);
  for (const [action, codes] of Object.entries(policy.actions ?? {})) {
    for (const [code, handle] of Object.entries(codes ?? {})) add(code, actionLabels[action] ?? action, handle);
  }
  return [...rows.values()].sort((a, b) => Number(a.code === FALLBACK) - Number(b.code === FALLBACK));
}

/** The overrides to save from the table's current state: only the flags that differ from the default. */
export function overridesFrom(
  rows: { code: string; defaults: Flags; review: boolean; notify: boolean }[],
): ErrorOverrides {
  const out: ErrorOverrides = {};
  for (const row of rows) {
    const flags: { review?: boolean; notify?: boolean } = {};
    if (row.review !== row.defaults.review) flags.review = row.review;
    if (row.notify !== row.defaults.notify) flags.notify = row.notify;
    if (Object.keys(flags).length) out[row.code] = flags;
  }
  return out;
}

/** One connection's "How errors are handled" rows, for the Alerts & health page's Error handling table. */
export interface ConnectionPolicy {
  id: string;
  name: string;
  provider: string;
  rows: PolicyRow[];
}

/**
 * Every connection whose provider declares an error policy, with its rows (connections keep their
 * order). A connection whose provider isn't installed, or declares no policy, is left out: there is no
 * default to compare against, and the server refuses overrides for it.
 */
export function connectionPolicies(
  connections: { id: string; name: string; provider: string; errorOverrides?: ErrorOverrides | null }[],
  providers: { slug: string; actions?: { key: string; label: string }[]; errorPolicy?: ErrorPolicyInfo | null }[],
): ConnectionPolicy[] {
  const bySlug = new Map(providers.map((p) => [p.slug, p]));
  return connections.flatMap((c) => {
    const provider = bySlug.get(c.provider);
    const labels = Object.fromEntries((provider?.actions ?? []).map((a) => [a.key, a.label]));
    const rows = policyRows(provider?.errorPolicy, labels, c.errorOverrides);
    return rows.length ? [{ id: c.id, name: c.name, provider: c.provider, rows }] : [];
  });
}
