// The sidebar's links to a package's views (viewLinks.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { sidebarViewLinks } from "./viewLinks.ts";

const view = (slug, sidebar, pkg = "screenplay-studio", name = "Timeline") => ({
  slug,
  name,
  package: pkg,
  definition: sidebar === undefined ? {} : { sidebar },
});

describe("sidebarViewLinks", () => {
  test("only a view that asks for one gets a link", () => {
    assert.deepEqual(
      sidebarViewLinks([view("a"), view("b", false), view("c", null), { slug: "d", name: "D", package: "p" }]),
      [],
    );
  });
  test("true links the view's page under its title", () => {
    assert.deepEqual(sidebarViewLinks([view("story-timeline", true)]), [
      {
        slug: "story-timeline",
        package: "screenplay-studio",
        label: "Timeline",
        icon: "🎞",
        href: "/workspace/views/story-timeline",
      },
    ]);
  });
  test("the view may name its own label and icon; a blank one falls back", () => {
    const [own] = sidebarViewLinks([view("story-timeline", { label: "Story timeline", icon: "🎬" })]);
    assert.equal(own.label, "Story timeline");
    assert.equal(own.icon, "🎬");
    const [blank] = sidebarViewLinks([view("story-timeline", { label: "  " })]);
    assert.equal(blank.label, "Timeline");
    assert.equal(blank.icon, "🎞");
    const [empty] = sidebarViewLinks([view("story-timeline", {})]);
    assert.equal(empty.label, "Timeline");
  });
});
