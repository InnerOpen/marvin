// The sidebar's package groups (collectionGroups.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { nameWithin, packageTitle, placePackages } from "./collectionGroups.ts";

const c = (id, name, packageSlug = null, integrationId = null) => ({ id, name, integrationId, packageSlug });

describe("packageTitle", () => {
  test("is what the names say before the colon, when they agree", () => {
    assert.equal(packageTitle("screenplay-studio", ["Screenplay Studio: Cast", "Screenplay Studio: Script"]), "Screenplay Studio");
  });
  test("falls back to the slug in words when the names disagree or have no colon", () => {
    assert.equal(packageTitle("screenplay-studio", ["Cast", "Script"]), "Screenplay studio");
    assert.equal(packageTitle("film-kit", ["A: x", "B: y"]), "Film kit");
  });
  test("prefers the package's own name to the slug when the names do not say", () => {
    assert.equal(packageTitle("timeline-demos", [], "Timeline Demos"), "Timeline Demos");
    assert.equal(packageTitle("screenplay-studio", ["Screenplay Studio: Cast"], "Studio"), "Screenplay Studio");
  });
});

describe("nameWithin", () => {
  test("drops the group's own prefix and capitalises what is left", () => {
    assert.equal(nameWithin("Screenplay Studio: Sound library", "Screenplay Studio"), "Sound library");
    assert.equal(nameWithin("screenplay studio: cast", "Screenplay Studio"), "Cast");
  });
  test("leaves a name that does not carry the prefix", () => {
    assert.equal(nameWithin("Featured", "Screenplay Studio"), "Featured");
  });
});

const link = (slug, pkg) => ({ slug, package: pkg, label: slug, icon: "🎞", href: `/workspace/views/${slug}` });
const place = (slug, sidebar, name = slug) => ({ slug, name, sidebar });
const slugs = (groups) => groups.map((g) => [g.slug, g.views.map((v) => v.slug), g.items.map((x) => x.id)]);

describe("placePackages", () => {
  const all = [c("1", "Screenplay Studio: Cast", "ss"), c("2", "Screenplay Studio: Script", "ss"), c("3", "Featured"), c("4", "n8n: Failed", null, "int-1"), c("5", "Only: One", "solo")];

  test("by default a package's collections and view links fold into one group under Collections, links first", () => {
    const placed = placePackages(all, [link("story-timeline", "ss")], []);
    assert.deepEqual(slugs(placed.nested), [["solo", [], ["5"]], ["ss", ["story-timeline"], ["1", "2"]]]);
    assert.deepEqual(placed.nested.map((g) => g.name), ["Only", "Screenplay Studio"]);
    assert.deepEqual(placed.sections, []);
  });
  test("keeps a person's collections and an integration's in the plain list", () => {
    const { loose } = placePackages(all, [], []);
    assert.deepEqual(loose.map((x) => x.id).sort(), ["3", "4"]);
  });
  test("under Collections a package that brings one thing still gets its group: a lone collection, and a lone view link", () => {
    const placed = placePackages([c("5", "Recordings", "media")], [link("agenda", "demo")], [place("media", "collections", "Media")]);
    assert.deepEqual(slugs(placed.nested), [["demo", ["agenda"], []], ["media", [], ["5"]]]);
    assert.deepEqual([placed.nested[1].name, placed.loose], ["Media", []]);
  });
  test("a group of view links alone is named for the package", () => {
    const placed = placePackages([], [link("agenda", "demo"), link("roster", "demo")], [place("demo", "collections", "Timeline Demos")]);
    assert.equal(placed.nested[0].name, "Timeline Demos");
  });
  test("its own section is what the person asked for, even for a single collection", () => {
    const placed = placePackages(all, [link("story-timeline", "ss")], [place("ss", "section"), place("solo", "section")]);
    assert.deepEqual(slugs(placed.sections), [["solo", [], ["5"]], ["ss", ["story-timeline"], ["1", "2"]]]);
    assert.deepEqual(placed.nested, []);
    assert.deepEqual(placed.loose.map((x) => x.id).sort(), ["3", "4"]);
  });
  test("hidden leaves out its collections and its view links, and nothing else", () => {
    const placed = placePackages(all, [link("story-timeline", "ss"), link("wall", "solo")], [place("ss", "hidden"), place("solo", "hidden")]);
    assert.deepEqual([placed.nested, placed.sections], [[], []]);
    assert.deepEqual(placed.loose.map((x) => x.id).sort(), ["3", "4"]);
  });
  test("a package with nothing shown gets no group or section", () => {
    assert.deepEqual(placePackages([c("3", "Featured")], [], [place("ss", "section")]).sections, []);
  });
  test("an integration's collection is never grouped by package, even if it has one", () => {
    const placed = placePackages([c("1", "A: x", "p", "int"), c("2", "A: y", "p", "int")], [], [place("p", "section")]);
    assert.deepEqual([placed.nested.length, placed.sections.length, placed.loose.length], [0, 0, 2]);
  });
  test("groups and sections are listed A to Z", () => {
    const four = [c("1", "Zed: a", "z"), c("2", "Zed: b", "z"), c("3", "Alpha: a", "a"), c("4", "Alpha: b", "a")];
    assert.deepEqual(placePackages(four, [], []).nested.map((g) => g.name), ["Alpha", "Zed"]);
    assert.deepEqual(placePackages(four, [], [place("z", "section"), place("a", "section")]).sections.map((g) => g.name), ["Alpha", "Zed"]);
  });
});
