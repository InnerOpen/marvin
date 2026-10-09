// Workflow Library helpers (workflowLibrary.ts): the setup form's pickers and starting values, the vars sent to
// configure, readiness, search and grouping. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  choicesFor,
  groupRecipes,
  initialValues,
  matches,
  readiness,
  recipeHref,
  recipeVars,
  setupPage,
  triggerText,
} from "./workflowLibrary.ts";

const refs = {
  entryTypes: [
    { slug: "campaign", name: "Campaign", fields: ["utm_source", "utm_medium"] },
    { slug: "newsletter-issue", name: "Newsletter issue", fields: ["body", "preview"] },
  ],
  integrations: [
    { slug: "newsletter", name: "Newsletter", provider: "buttondown", enabled: true },
    { slug: "old-newsletter", name: "Old", provider: "buttondown", enabled: false },
    { slug: "alerts", name: "Alerts", provider: "apprise", enabled: true },
  ],
  collections: [{ slug: "featured", name: "Featured" }],
  outgoingWebhooks: [{ id: "w-1", name: "Announce" }],
  incomingWebhooks: [{ slug: "forms", name: "Forms", enabled: true }],
  statuses: ["approved", "draft", "needs_review", "published"],
};

function recipe(overrides = {}) {
  return {
    id: "newsletter-delivery",
    title: "Newsletter delivery",
    outcome: "A published newsletter entry becomes a Buttondown issue.",
    category: "Publishing and editorial",
    categorySlug: "publishing",
    tags: ["newsletter", "buttondown"],
    trigger: { type: "event", event: "entry_published" },
    status: "verified-current",
    shape: "workflow",
    providers: ["buttondown"],
    sideEffects: [],
    setupVariables: [
      { name: "body_field", type: "field_key", description: "", example: "body" },
      { name: "newsletter_entry_type", type: "entry_type_slug", description: "", example: "newsletter-issue" },
      { name: "newsletter_integration", type: "integration_slug", description: "", example: "buttondown" },
    ],
    supportingObjects: [],
    dependencies: [],
    missing: [],
    ...overrides,
  };
}

const variable = (r, name) => r.setupVariables.find((v) => v.name === name);

describe("choicesFor", () => {
  test("an integration picker offers only enabled connections of the recipe's provider", () => {
    const r = recipe();
    const picker = choicesFor(variable(r, "newsletter_integration"), r, refs);
    assert.deepEqual(picker, { input: "select", choices: [{ value: "newsletter", label: "Newsletter" }] });
  });

  test("an integration picker with nothing connected says what to connect, and where", () => {
    const r = recipe({ providers: ["n8n"] });
    const picker = choicesFor(variable(r, "newsletter_integration"), r, refs);
    assert.deepEqual(picker.choices, []);
    assert.match(picker.empty.text, /n8n/);
    assert.equal(picker.empty.href, "/workspace/settings/integrations");
  });

  test("a field key offers the fields of the entry type chosen, and asks for one until then", () => {
    const r = recipe();
    const field = variable(r, "body_field");
    assert.equal(choicesFor(field, r, refs, {}).empty.text, "Choose the entry type first.");
    const picker = choicesFor(field, r, refs, { newsletter_entry_type: "campaign" });
    assert.deepEqual(picker.choices.map((c) => c.value), ["utm_source", "utm_medium"]);
  });

  test("an incoming webhook picker always offers “any”", () => {
    const r = recipe({ setupVariables: [{ name: "hook", type: "incoming_webhook_slug", description: "" }] });
    const picker = choicesFor(r.setupVariables[0], r, refs);
    assert.deepEqual(picker.choices.map((c) => c.value), ["any", "forms"]);
  });

  test("collections by slug or by name, statuses, webhooks, and free input", () => {
    const r = recipe();
    const pick = (type) => choicesFor({ name: "x", type, description: "" }, r, refs);
    assert.deepEqual(pick("collection_slug").choices, [{ value: "featured", label: "Featured" }]);
    assert.deepEqual(pick("collection_name").choices, [{ value: "Featured", label: "Featured" }]);
    assert.deepEqual(pick("webhook_id").choices, [{ value: "w-1", label: "Announce" }]);
    assert.equal(pick("status").choices.find((c) => c.value === "needs_review").label, "needs review");
    assert.deepEqual(pick("integer"), { input: "integer" });
    assert.deepEqual(pick("text"), { input: "text" });
  });
});

describe("initialValues", () => {
  test("starts from the example when it is a choice here, else the only choice — entry type before its fields", () => {
    const r = recipe();
    assert.deepEqual(initialValues(r, refs), {
      newsletter_entry_type: "newsletter-issue",
      newsletter_integration: "newsletter", // the example "buttondown" is a provider, not a slug here: the only choice
      body_field: "body",
    });
  });

  test("keeps a value that is still a choice and resets a field the new entry type doesn't have", () => {
    const r = recipe();
    const values = initialValues(r, refs, { newsletter_entry_type: "campaign", body_field: "body", newsletter_integration: "newsletter" });
    assert.equal(values.newsletter_entry_type, "campaign");
    assert.equal(values.body_field, "");
  });

  test("an integer starts at its example; text starts blank", () => {
    const r = recipe({
      setupVariables: [
        { name: "interval_seconds", type: "integer", description: "", example: 3600 },
        { name: "path", type: "text", description: "", example: "editorial-tasks" },
      ],
    });
    assert.deepEqual(initialValues(r, refs), { interval_seconds: "3600", path: "" });
  });
});

describe("recipeVars", () => {
  test("sends integers as numbers and names the blanks", () => {
    const r = recipe({
      setupVariables: [
        { name: "interval_seconds", type: "integer", description: "" },
        { name: "path", type: "text", description: "" },
      ],
    });
    assert.deepEqual(recipeVars(r, { interval_seconds: " 7200 ", path: "" }), { vars: { interval_seconds: 7200 }, blank: ["path"] });
    assert.deepEqual(recipeVars(r, { interval_seconds: "hourly", path: "x" }).vars, { interval_seconds: "hourly", path: "x" });
  });
});

describe("readiness and search", () => {
  const ready = recipe();
  const needsSetup = recipe({ id: "a", missing: ["needs a connected n8n integration"] });
  const elsewhere = recipe({ id: "b", shape: "configuration", status: "supported-after-configuration" });
  const idea = recipe({ id: "c", shape: "idea", status: "needs-engine-capability", title: "Translation desk", tags: ["ai"] });

  test("readiness follows the shape, then what is missing", () => {
    assert.deepEqual([ready, needsSetup, elsewhere, idea].map(readiness), ["ready", "setup", "elsewhere", "idea"]);
  });

  test("the default filter shows what can be used here (ready or needs setup)", () => {
    const shown = [ready, needsSetup, elsewhere, idea].filter((r) => matches(r, "", { readiness: "usable" }));
    assert.deepEqual(shown.map((r) => r.id), ["newsletter-delivery", "a"]);
    assert.deepEqual([ready, idea].filter((r) => matches(r, "", { readiness: "idea" })).map((r) => r.id), ["c"]);
  });

  test("every word of the query must match the title, outcome, tags, category or trigger", () => {
    assert.ok(matches(ready, "buttondown published"));
    assert.ok(matches(ready, "Newsletter"));
    assert.ok(!matches(ready, "buttondown slack"));
    assert.ok(!matches(ready, "", { category: "media" }));
  });

  test("groups keep catalogue order and put ready recipes first", () => {
    const groups = groupRecipes([idea, needsSetup, ready, recipe({ id: "m", categorySlug: "media", category: "Images" })]);
    assert.deepEqual(groups.map((g) => g.slug), ["publishing", "media"]);
    assert.deepEqual(groups[0].recipes.map((r) => r.id), ["newsletter-delivery", "a", "c"]);
  });
});

describe("words and links", () => {
  test("triggers in words", () => {
    assert.equal(triggerText({ type: "event", event: "entry_published" }), "When entry published");
    assert.equal(triggerText({ type: "manual" }), "When you run it");
    assert.equal(triggerText({ type: "subscription", event: "webhook_triggered" }), "When webhook triggered (a subscription, not a workflow)");
  });

  test("a configuration part links to the page it is set up on", () => {
    assert.equal(setupPage("notification_settings").href, "/automation/notifications");
    assert.equal(setupPage("integration_event_subscription", recipe({ trigger: { type: "subscription", event: "webhook_triggered" } })).href, "/automation/events/webhook_triggered");
    assert.equal(setupPage("native"), null);
  });

  test("the editor's deep link", () => {
    assert.equal(recipeHref("utm-librarian"), "/automation/workflows?recipe=utm-librarian");
  });
});
