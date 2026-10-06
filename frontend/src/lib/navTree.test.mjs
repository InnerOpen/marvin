// The breadcrumb map (navTree.ts) and the pages that use it. Run with `npm test`.
// Every admin, settings, automation and publishing page declares its node with `crumb="…"` and leaves the trail to the
// layout: no page of its own breadcrumb, "Back to …" link or eyebrow. Content pages (entries, collections, assets,
// resources) are out of scope for now.

import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { describe, test } from "node:test";

import { NAV_NODE_LIST, NAV_NODES, navHref, navTitle, navTrail } from "./navTree.ts";

const PAGES = new URL("../pages/", import.meta.url);
const SCOPE = ["admin", "automation", "publishing", "workspace"];
const CONTENT = /^workspace\/(assets|collections|entries|resources)(\/|\.astro$)/;

/** Page files under `dir`, relative to pages/ ("admin/users/[id].astro"). */
function pageFiles(dir) {
  const out = [];
  for (const name of readdirSync(new URL(`${dir}/`, PAGES))) {
    const rel = `${dir}/${name}`;
    if (statSync(new URL(rel, PAGES)).isDirectory()) out.push(...pageFiles(rel));
    else if (name.endsWith(".astro")) out.push(rel);
  }
  return out;
}

/** "admin/users/[id].astro" → "/admin/users/[id]"; "admin/index.astro" → "/admin". */
const routeOf = (file) => `/${file.replace(/\.astro$/, "").replace(/(^|\/)index$/, "")}`;

/** The page file a node's href lands on, ignoring ?query and #hash. */
function fileFor(href) {
  const path = href.replace(/[?#].*$/, "").replace(/^\//, "");
  return [`${path}.astro`, `${path}/index.astro`].find((f) => existsSync(new URL(f, PAGES)));
}

/** The opening <AppLayout …> / <AdminLayout …> tag, or null for a page without one (a redirect). */
function layoutTag(source) {
  const match = source.match(/<(AppLayout|AdminLayout)\b[\s\S]*?>\s*\n/);
  return match ? match[0] : null;
}

const inScope = SCOPE.flatMap(pageFiles)
  .filter((f) => !CONTENT.test(f))
  .map((file) => ({ file, source: readFileSync(new URL(file, PAGES), "utf8") }))
  .filter(({ source }) => layoutTag(source));

describe("nav map", () => {
  test("ids and hrefs are unique", () => {
    const ids = NAV_NODE_LIST.map((n) => n.id);
    const hrefs = NAV_NODE_LIST.map((n) => n.href);
    assert.deepEqual(
      ids.filter((id, i) => ids.indexOf(id) !== i),
      [],
    );
    assert.deepEqual(
      hrefs.filter((href, i) => hrefs.indexOf(href) !== i),
      [],
    );
  });

  test("every parent exists and no trail loops", () => {
    for (const node of NAV_NODE_LIST) {
      if (node.parent) assert.ok(NAV_NODES.has(node.parent), `${node.id}: parent "${node.parent}" is not in the map`);
      assert.doesNotThrow(() => navTrail(node.id), node.id);
    }
  });

  test("every href lands on a page", () => {
    for (const node of NAV_NODE_LIST) assert.ok(fileFor(node.href), `${node.id}: no page for ${node.href}`);
  });

  test("trails list the ancestors, root first, with params and labels filled in", () => {
    assert.deepEqual(navTrail("admin"), []);
    assert.deepEqual(navTrail("settings.email.smtp"), [
      { label: "Settings", href: "/workspace/settings" },
      { label: "Email", href: "/workspace/settings/email" },
    ]);
    assert.deepEqual(
      navTrail("automation.events.type.webhook", {
        params: { type: "entry_published" },
        labels: { "automation.events.type": "Entry published" },
      }),
      [
        { label: "Automation", href: "/workspace/settings?tab=automation" },
        { label: "Events", href: "/automation/events" },
        { label: "Entry published", href: "/automation/events/entry_published" },
      ],
    );
    assert.equal(navHref("admin.users.user", { id: "a b" }), "/admin/users/a%20b");
    assert.equal(navTitle("admin"), "Overview");
    assert.equal(navTitle("admin.users"), "Users");
    assert.throws(() => navTrail("no.such.page"), /Unknown nav node/);
  });
});

describe("pages use the map", () => {
  test("the scope is what we expect", () => {
    assert.ok(inScope.length >= 60, `only ${inScope.length} in-scope pages found`);
  });

  for (const { file, source } of inScope) {
    test(file, () => {
      const tag = layoutTag(source);
      const crumb = tag.match(/\scrumb="([^"]+)"/)?.[1];
      assert.ok(crumb, 'the layout has no crumb="…"');
      assert.ok(NAV_NODES.has(crumb), `crumb "${crumb}" is not in lib/navTree.ts`);
      assert.equal(
        NAV_NODES.get(crumb).href.replace(/[?#].*$/, ""),
        routeOf(file),
        `"${crumb}" points at another page`,
      );
      assert.doesNotMatch(tag, /\seyebrow=/, "the trail replaces the eyebrow");
      assert.doesNotMatch(source, /<Breadcrumb\b|class="breadcrumb"/, "the layout renders the breadcrumb");
      assert.doesNotMatch(
        source,
        /<a\b[^>]*>\s*(?:←|&larr;|‹)?\s*Back\b[^<]*<\/a>/,
        "a Back link — the trail is the way back",
      );
    });
  }

  test("every page node is declared by exactly one page", () => {
    const declared = inScope.map(({ source }) => layoutTag(source).match(/\scrumb="([^"]+)"/)?.[1]);
    for (const node of NAV_NODE_LIST) {
      if (node.href.includes("?")) continue; // a hub tab (Automation, Publishing), not a page of its own
      assert.equal(declared.filter((c) => c === node.id).length, 1, `${node.id} (${node.href})`);
    }
  });
});
