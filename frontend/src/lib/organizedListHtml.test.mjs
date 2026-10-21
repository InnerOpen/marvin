// HTML the shared list kit draws (organizedListHtml.ts): section headings, the card's ⋯ menu and On/Off switch.
// Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { menuHtml, sectionsHtml, switchHtml } from "./organizedListHtml.ts";

const section = (extra = {}) => ({
  key: "yours",
  kind: "yours",
  title: "Yours",
  items: [{ id: "a" }],
  count: 3,
  on: 2,
  ...extra,
});

describe("sections", () => {
  test("a heading with the title and counts, then each item through the page's renderer", () => {
    const html = sectionsHtml([section()], {
      noun: "workflow",
      integrations: {},
      renderItem: (i, { linked }) => `<i data-id="${i.id}" data-linked="${linked}"></i>`,
    });
    assert.match(html, /<section class="org-section" data-section="yours">/);
    assert.match(html, /<span class="org-name">Yours<\/span>/);
    assert.match(html, /3 workflows, 2 on/);
    assert.match(html, /<i data-id="a" data-linked="false"><\/i>/);
  });

  test("an integration's heading carries its logo mark and an escaped name", () => {
    const html = sectionsHtml(
      [section({ key: "integration:b1", kind: "integration", title: "<Bold> & Co", integrationId: "b1" })],
      {
        noun: "workflow",
        integrations: { b1: { name: "x", slug: "buttondown", hasLogo: true } },
        renderItem: () => "",
      },
    );
    assert.match(html, /class="int-mark"/);
    assert.match(html, /&lt;Bold&gt; &amp; Co/);
    assert.doesNotMatch(html, /<Bold>/);
  });

  test("marks the linked item", () => {
    const html = sectionsHtml([section()], {
      noun: "workflow",
      integrations: {},
      linkedId: "a",
      id: (i) => i.id,
      renderItem: (_i, { linked }) => String(linked),
    });
    assert.match(html, />true</);
  });
});

describe("card controls", () => {
  test("the ⋯ menu lists its actions, each keeping the page's class, hidden until opened", () => {
    const html = menuHtml([
      { cls: "js-copy", label: "Copy JSON", title: "Copy it" },
      { cls: "js-delete", label: "Delete", danger: true },
    ]);
    assert.match(html, /class="org-more"[^>]*aria-expanded="false"/);
    assert.match(html, /<div class="org-menu" role="menu" hidden>/);
    assert.match(html, /class="org-menu-item js-copy" role="menuitem" title="Copy it">Copy JSON</);
    assert.match(html, /org-menu-item danger js-delete/);
  });

  test("the switch says On or Off to everyone, and escapes the label", () => {
    const on = switchHtml({ on: true, cls: "js-toggle", label: 'Workflow "A"' });
    assert.match(on, /role="switch" aria-checked="true"/);
    assert.match(on, /aria-label="Workflow &quot;A&quot;: on"/);
    assert.match(switchHtml({ on: false, cls: "js-toggle", label: "w" }), /aria-checked="false"/);
  });
});
