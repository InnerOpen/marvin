/**
 * Marvin — per-page context ("what am I looking at?").
 *
 * Pages *declare* their grounding: AppLayout stamps `data-entity-type` / `data-entity-id` /
 * `data-entity-label` onto <body>, and we read it back here. We deliberately do NOT scrape the
 * DOM or guess from markup — a declared contract stays correct as pages change. The route is
 * always available as a fallback so the bubble at least knows where it is.
 *
 * Grounding only: this changes what Marvin *knows*, never what he's *allowed to do*.
 * `min_role` + `invocation_sources` remain the permission wall, enforced server-side.
 */

export interface PageContext {
  /** "entry" | "asset" | "resource" | "collection" — whatever the page declared. */
  entityType?: string;
  entityId?: string;
  /** Human-readable name, for the context chip. Never sent to the API. */
  entityLabel?: string;
  route: string;
}

/**
 * The user can dismiss context for the current page (the × on the chip) when they want to ask
 * about something unrelated. Module-level and deliberately not persisted: a full page navigation
 * resets it, which matches the mental model of "this page's context".
 */
let suppressed = false;

export function setContextSuppressed(value: boolean): void {
  suppressed = value;
}

export function isContextSuppressed(): boolean {
  return suppressed;
}

/** Read the context the current page declared. */
export function getPageContext(): PageContext {
  const data = document.body?.dataset ?? ({} as DOMStringMap);
  return {
    entityType: data.entityType || undefined,
    entityId: data.entityId || undefined,
    entityLabel: data.entityLabel || undefined,
    route: typeof location !== "undefined" ? location.pathname : "",
  };
}

/**
 * The context to actually send with a request: null when the page declared none or the user
 * dismissed it. Callers can spread the result without branching on suppression themselves.
 */
export function getActiveContext(): PageContext | null {
  if (suppressed) return null;
  const ctx = getPageContext();
  return ctx.entityType && ctx.entityId ? ctx : null;
}

/** Label for the chip, e.g. "Entry · Chore Coat" (falls back to the type alone). */
export function contextLabel(ctx: PageContext | null): string | null {
  if (!ctx?.entityType || !ctx.entityId) return null;
  const type = ctx.entityType.charAt(0).toUpperCase() + ctx.entityType.slice(1);
  return ctx.entityLabel ? `${type} · ${ctx.entityLabel}` : type;
}
