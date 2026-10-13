// The Workflow Library as people see it (GET /api/automations/library): the setup form's pickers, what a recipe
// needs before it can be used here, and search. Pure, so `npm test` covers it (workflowLibrary.test.mjs); the
// Library page and the workflow editor's "Start from a recipe" dialog both use it.

export interface RecipeVariable {
  name: string;
  /** Which picker: entry_type_slug, field_key, entry_date, integration_slug, webhook_id, incoming_webhook_slug,
   *  collection_slug, collection_name, status — or free input: text, integer. */
  type: string;
  description: string;
  example?: unknown;
}

export interface RecipeUse {
  id: string;
  name: string;
  slug: string;
  enabled: boolean;
  outdated?: boolean;
}

export interface RecipeSource {
  provider: string;
  name: string;
  package?: string | null;
  version?: string | null;
}

/** "From the Slack plugin 0.4.0" for an integration's recipe; null for Marvin's own. */
export const sourceText = (recipe: Pick<Recipe, "source">): string | null =>
  recipe.source
    ? `From the ${recipe.source.name} plugin${recipe.source.version ? ` ${recipe.source.version}` : ""}`
    : null;

/** Where a workflow made from a recipe opens. */
export const workflowHref = (id: string) => `/automation/workflows?workflow=${encodeURIComponent(id)}`;

export interface Recipe {
  id: string;
  title: string;
  outcome: string;
  category: string;
  categorySlug: string;
  tags: string[];
  trigger: { type: string; event?: string | null; note?: string | null };
  status: string;
  /** workflow (fills the builder) | configuration (set up on existing pages) | idea (needs a capability). */
  shape: "workflow" | "configuration" | "idea" | string;
  providers: string[];
  /** What a connected integration must be able to do instead of a named provider (notify: Slack, Apprise…). */
  capabilities?: string[];
  /** This workspace's workflows made from it; `outdated`: the recipe has changed since. */
  inUse?: RecipeUse[];
  /** An installed integration's recipe: which plugin ships it (absent for Marvin's own). */
  source?: RecipeSource | null;
  sideEffects: { kind: string; description: string }[];
  setupVariables: RecipeVariable[];
  supportingObjects: { kind: string; name: string; purpose: string; required: boolean }[];
  dependencies: { capability: string; why: string }[];
  /** Why this workspace can't use it yet; empty: ready here. */
  missing: string[];
}

export interface LibraryRefs {
  /** `dateFields`: those of `fields` that hold a date or a date and time. */
  entryTypes: { slug: string; name: string; fields: string[]; dateFields?: string[] }[];
  integrations: { slug: string; name: string; provider: string; enabled: boolean; capabilities?: string[] }[];
  collections: { slug?: string | null; name: string }[];
  outgoingWebhooks: { id?: string | null; name: string }[];
  incomingWebhooks: { slug?: string | null; name: string; enabled?: boolean | null }[];
  statuses: string[];
}

export interface WorkflowLibrary {
  recipes: Recipe[];
  capabilities: Record<string, { name: string; priority: string; acceptance: string }>;
  refs: LibraryRefs;
}

export interface Choice {
  value: string;
  label: string;
}

/** What one setup variable renders as: a picker of this workspace's names, or a free input. `empty` says what to
 * do when the picker has nothing to offer (and `href` where). */
export type Picker =
  | { input: "select"; choices: Choice[]; empty?: { text: string; href?: string } }
  | { input: "text" }
  | { input: "integer" };

export type Values = Record<string, string>;

export type Readiness = "ready" | "setup" | "elsewhere" | "idea";

export const READINESS_LABEL: Record<Readiness, string> = {
  ready: "Ready here",
  setup: "Needs setup",
  elsewhere: "Set up elsewhere",
  idea: "Not possible yet",
};

/** The readiness filter's values: "usable" (the default) is ready or needs setup. */
export const READINESS_FILTERS: Choice[] = [
  { value: "usable", label: "Ready here or needs setup" },
  { value: "ready", label: READINESS_LABEL.ready },
  { value: "setup", label: READINESS_LABEL.setup },
  { value: "elsewhere", label: READINESS_LABEL.elsewhere },
  { value: "idea", label: READINESS_LABEL.idea },
];

const INTEGRATIONS_HREF = "/workspace/settings/integrations";

export function readiness(recipe: Recipe): Readiness {
  if (recipe.shape === "configuration") return "elsewhere";
  if (recipe.shape !== "workflow") return "idea";
  return recipe.missing.length ? "setup" : "ready";
}

const humanize = (value: string): string => value.replace(/[_-]+/g, " ");

/** The entry type a field picker belongs to: the nearest one set up before it (a recipe that drafts into a second
 * type names that type just before its fields), else the recipe's first. */
function entryTypeVariable(recipe: Recipe, variable: RecipeVariable): RecipeVariable | undefined {
  const types = recipe.setupVariables.filter((v) => v.type === "entry_type_slug");
  const at = recipe.setupVariables.indexOf(variable);
  return types.filter((v) => recipe.setupVariables.indexOf(v) < at).at(-1) ?? types[0];
}

const chosenType = (variable: RecipeVariable, recipe: Recipe, refs: LibraryRefs, values: Values) => {
  const typeVar = entryTypeVariable(recipe, variable);
  return typeVar ? refs.entryTypes.find((t) => t.slug === values[typeVar.name]) : undefined;
};

/** The dates every entry has, whatever its type's fields (`${entry.<value>}`). */
export const ENTRY_DATES: Choice[] = [
  { value: "publish_at", label: "Scheduled publish date (every entry)" },
  { value: "expire_at", label: "Expiry date (every entry)" },
  { value: "published_at", label: "Published date (every entry)" },
  { value: "created_at", label: "Created date (every entry)" },
  { value: "updated_at", label: "Last edited (every entry)" },
];

/** Pickers whose choices depend on an entry type chosen in another picker. */
const DEPENDS_ON_TYPE = new Set(["field_key", "entry_date"]);

function select(choices: Choice[], empty: { text: string; href?: string }): Picker {
  return { input: "select", choices, ...(choices.length ? {} : { empty }) };
}

/** The picker for one setup variable, from this workspace's names. A field_key (or entry_date) offers the fields
 * (or dates) of the entry type chosen just before it (`values`), so it changes when that does. */
export function choicesFor(variable: RecipeVariable, recipe: Recipe, refs: LibraryRefs, values: Values = {}): Picker {
  switch (variable.type) {
    case "entry_type_slug":
      return select(
        refs.entryTypes.map((t) => ({ value: t.slug, label: t.name })),
        { text: "No entry types yet.", href: "/workspace/entry-types/new" },
      );
    case "field_key": {
      const chosen = chosenType(variable, recipe, refs, values);
      if (!chosen) return { input: "select", choices: [], empty: { text: "Choose the entry type first." } };
      return select(
        chosen.fields.map((key) => ({ value: key, label: key })),
        { text: `“${chosen.name}” has no fields.`, href: "/workspace/entry-types" },
      );
    }
    case "entry_date": {
      // The type's own date fields first (`data.<key>`), then the dates every entry has — so there's always one.
      const own = (chosenType(variable, recipe, refs, values)?.dateFields ?? []).map((key) => ({ value: `data.${key}`, label: key }));
      return select([...own, ...ENTRY_DATES], { text: "" });
    }
    case "integration_slug": {
      // A named provider (Buttondown, n8n…), or any integration that can do what the recipe needs (notify).
      const wanted = new Set(recipe.providers);
      const able = new Set(recipe.capabilities ?? []);
      const fits = (i: LibraryRefs["integrations"][number]) =>
        (!wanted.size && !able.size) || wanted.has(i.provider) || (i.capabilities ?? []).some((c) => able.has(c));
      const connected = refs.integrations.filter((i) => i.enabled && fits(i));
      const needs = recipe.providers.length
        ? `a connected ${recipe.providers.join(" or ")} integration`
        : able.size
          ? `a connected integration that can ${[...able].join(" and ")} (Slack, Apprise…)`
          : "a connected integration";
      return select(
        connected.map((i) => ({ value: i.slug, label: i.name })),
        { text: `This needs ${needs}.`, href: INTEGRATIONS_HREF },
      );
    }
    case "webhook_id":
      return select(
        refs.outgoingWebhooks.filter((w) => w.id).map((w) => ({ value: String(w.id), label: w.name })),
        { text: "No outgoing webhooks yet.", href: "/automation/webhooks/new" },
      );
    case "incoming_webhook_slug":
      return select(
        [
          { value: "any", label: "Any incoming webhook" },
          ...refs.incomingWebhooks.filter((w) => w.slug).map((w) => ({ value: String(w.slug), label: w.name })),
        ],
        { text: "" },
      );
    case "collection_slug":
      return select(
        refs.collections.filter((c) => c.slug).map((c) => ({ value: String(c.slug), label: c.name })),
        { text: "No collections yet.", href: "/workspace/collections" },
      );
    case "collection_name":
      return select(
        refs.collections.map((c) => ({ value: c.name, label: c.name })),
        { text: "No collections yet.", href: "/workspace/collections" },
      );
    case "status":
      return select(
        refs.statuses.map((s) => ({ value: s, label: humanize(s) })),
        { text: "" },
      );
    case "integer":
    case "number":
      return { input: "integer" };
    default:
      return { input: "text" };
  }
}

/** The setup values to start from: each picker's example when it is one of the choices here, else its only
 * choice, else blank; an integer starts at its example; text starts blank (the example is a placeholder). A value
 * in `current` that is still a choice is kept — so changing the entry type resets only the fields it no longer
 * has. Entry types are settled before the field keys that depend on them. */
export function initialValues(recipe: Recipe, refs: LibraryRefs, current: Values = {}): Values {
  const values: Values = {};
  const ordered = [...recipe.setupVariables].sort(
    (a, b) => Number(DEPENDS_ON_TYPE.has(a.type)) - Number(DEPENDS_ON_TYPE.has(b.type)),
  );
  for (const variable of ordered) {
    const picker = choicesFor(variable, recipe, refs, values);
    const kept = current[variable.name];
    const example = variable.example == null ? "" : String(variable.example);
    if (picker.input === "select") {
      const offered = (value: string) => picker.choices.some((c) => c.value === value);
      if (kept && offered(kept)) values[variable.name] = kept;
      else if (example && offered(example)) values[variable.name] = example;
      else values[variable.name] = picker.choices.length === 1 ? picker.choices[0].value : "";
    } else if (picker.input === "integer") {
      values[variable.name] = kept ?? example;
    } else {
      values[variable.name] = kept ?? "";
    }
  }
  return values;
}

/** The `vars` to send to configure (integers as numbers), or the variables still blank. */
export function recipeVars(recipe: Recipe, values: Values): { vars: Record<string, string | number>; blank: string[] } {
  const vars: Record<string, string | number> = {};
  const blank: string[] = [];
  for (const variable of recipe.setupVariables) {
    const raw = (values[variable.name] ?? "").trim();
    if (!raw) {
      blank.push(variable.name);
      continue;
    }
    const isNumber = variable.type === "integer" || variable.type === "number";
    vars[variable.name] = isNumber && /^-?\d+(\.\d+)?$/.test(raw) ? Number(raw) : raw;
  }
  return { vars, blank };
}

export interface LibraryFilters {
  category?: string;
  /** A Readiness, or "usable" (ready or needs setup); blank: all. */
  readiness?: string;
}

/** Whether the recipe is shown for this search and these filters. Every word of the query must appear somewhere
 * in its title, outcome, category, tags or trigger. */
export function matches(recipe: Recipe, query: string, filters: LibraryFilters = {}): boolean {
  if (filters.category && recipe.categorySlug !== filters.category) return false;
  const state = readiness(recipe);
  if (
    filters.readiness === "usable"
      ? state !== "ready" && state !== "setup"
      : filters.readiness && state !== filters.readiness
  ) {
    return false;
  }
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const haystack = [recipe.title, recipe.outcome, recipe.category, ...recipe.tags, triggerText(recipe.trigger)]
    .join(" ")
    .toLowerCase();
  return words.every((word) => haystack.includes(word));
}

const READINESS_ORDER: Readiness[] = ["ready", "setup", "elsewhere", "idea"];

/** Recipes grouped by category (catalogue order), ready ones first within each group. */
export function groupRecipes(recipes: Recipe[]): { category: string; slug: string; recipes: Recipe[] }[] {
  const groups = new Map<string, { category: string; slug: string; recipes: Recipe[] }>();
  for (const recipe of recipes) {
    const group = groups.get(recipe.categorySlug) ?? {
      category: recipe.category,
      slug: recipe.categorySlug,
      recipes: [],
    };
    group.recipes.push(recipe);
    groups.set(recipe.categorySlug, group);
  }
  for (const group of groups.values()) {
    group.recipes.sort((a, b) => READINESS_ORDER.indexOf(readiness(a)) - READINESS_ORDER.indexOf(readiness(b)));
  }
  return [...groups.values()];
}

/** When the recipe runs, in words. */
export function triggerText(trigger: Recipe["trigger"]): string {
  const event = trigger.event ? humanize(trigger.event) : "";
  switch (trigger.type) {
    case "event":
      return event ? `When ${event}` : "When an event happens";
    case "manual":
      return "When you run it";
    case "schedule":
      return "On a schedule";
    case "incoming_webhook":
      return "When an incoming webhook is called";
    case "on_error":
      return "When a workflow fails";
    case "subscription":
      return event ? `When ${event} (a subscription, not a workflow)` : "On an event subscription";
    default:
      return humanize(trigger.type);
  }
}

export const SIDE_EFFECT_LABEL: Record<string, string> = {
  content_mutation: "Changes your content",
  external_post: "Posts to another service",
  paid_call: "Makes paid calls",
  notification: "Sends notifications",
  email: "Sends email",
};

/** Where a configuration recipe's part is set up, or null when it isn't a Marvin page (an app permission). */
export function setupPage(kind: string, recipe?: Recipe): { label: string; href: string } | null {
  switch (kind) {
    case "email_event_subscription":
      return { label: "Email settings", href: "/workspace/settings/email" };
    case "notification_settings":
      return { label: "Notifications", href: "/automation/notifications" };
    case "outgoing_webhook":
      return { label: "Webhooks", href: "/automation/webhooks/new" };
    case "incoming_webhook":
      return { label: "Incoming webhooks", href: "/automation/incoming-webhooks" };
    case "integration_connection":
      return { label: "Integrations", href: INTEGRATIONS_HREF };
    case "integration_event_subscription": {
      const event = recipe?.trigger.event;
      return {
        label: "the event’s page",
        href: event ? `/automation/events/${encodeURIComponent(event)}` : "/automation/events",
      };
    }
    case "scheduled_task":
      return { label: "Scheduled tasks", href: "/workspace/scheduled-tasks/new" };
    default:
      return null;
  }
}

/** The workflow editor's deep link that opens "Start from a recipe" on this recipe. */
export const recipeHref = (id: string): string => `/automation/workflows?recipe=${encodeURIComponent(id)}`;
