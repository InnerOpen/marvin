/**
 * The Agents page's permission-matrix editor, the DOM-free parts: what a row's "Default (…)" choice says,
 * which tools a built-in agent's editor lists, and whether a built-in's matrix is its code default.
 * Runs under `node --test` (agentMatrix.test.mjs); ai-agents.astro renders the result.
 */

export type PolicyValue = "allow" | "ask" | "block";

export const POLICY_LABELS: Record<PolicyValue, string> = { allow: "Allow", ask: "Ask first", block: "Block" };

interface Category {
  id: string;
  writes: boolean;
}
interface Tool {
  name: string;
  category: string;
}

/**
 * The label of a matrix row's "no entry" choice. `inherited` is what the row does with no entry, as the
 * server resolves it (`rows[].inherited` from GET /agents/{slug}/permissions) — what a built-in's editor
 * passes, since a built-in's defaults are its own (Marvin allows its in-workspace writes and asks before
 * workflow runs and external writes). Without it the custom-agent defaults apply: reads allow, writes ask
 * first with Allow writes on and are blocked with it off.
 */
export function inheritLabel(category: Category, allowWrites: boolean, inherited?: PolicyValue | null): string {
  if (inherited) return `Default (${POLICY_LABELS[inherited].toLowerCase()})`;
  if (!category.writes) return "Default (allow)";
  return allowWrites ? "Default (ask first — writes on)" : "Default (block — read-only)";
}

/** `{category id: inherited decision}` from a permissions response's rows (rows without one are left out). */
export function inheritedDefaults(rows: { id: string; inherited?: PolicyValue | null }[]): Record<string, PolicyValue> {
  const out: Record<string, PolicyValue> = {};
  for (const r of rows) if (r.inherited) out[r.id] = r.inherited;
  return out;
}

/**
 * The tools an agent's editor lists: all of them, or only the allowlisted ones for an agent with an
 * allowlist (the `ask` built-in) — Allow can't reach past an allowlist, so the others would be noise.
 */
export function matrixTools<T extends Tool>(tools: T[], allowlist?: string[] | null): T[] {
  if (!allowlist) return tools;
  const allowed = new Set(allowlist);
  return tools.filter((t) => allowed.has(t.name));
}

/**
 * Which category rows an editor shows: those with a listed tool, plus the external-MCP rows (their tools
 * are discovered at run time) unless an allowlist limits the agent to named tools.
 */
export function matrixCategories<C extends Category>(categories: C[], tools: Tool[], allowlist?: string[] | null): C[] {
  const used = new Set(tools.map((t) => t.category));
  return categories.filter((c) => used.has(c.id) || (!allowlist && c.id.startsWith("mcp")));
}

/** "Changed" when the workspace overrode a built-in's matrix, else "Default". */
export function matrixState(agent: { toolPolicyOverridden?: boolean | null }): "Default" | "Changed" {
  return agent.toolPolicyOverridden ? "Changed" : "Default";
}

/** A matrix as the API stores it: only explicit choices, and null when there are none (back to the defaults). */
export function policyFromChoices(choices: [string, string][]): Record<string, PolicyValue> | null {
  const out: Record<string, PolicyValue> = {};
  for (const [key, value] of choices)
    if (key && (value === "allow" || value === "ask" || value === "block")) out[key] = value;
  return Object.keys(out).length ? out : null;
}
