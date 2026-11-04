// The sidebar's package groups (collectionGroups.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { groupByPackage, nameWithin, packageTitle } from "./collectionGroups.ts";

const c = (id, name, packageSlug = null, integrationId = null) => ({ id, name, integrationId, packageSlug });

describe("packageTitle", () => {
  test("is what the names say before the colon, when they agree", () => {
    assert.equal(packageTitle("screenplay-studio", ["Screenplay Studio: Cast", "Screenplay Studio: Script"]), "Screenplay Studio");
  });
  test("falls back to the slug in words when the names disagree or have no colon", () => {
    assert.equal(packageTitle("screenplay-studio", ["Cast", "Script"]), "Screenplay studio");
    assert.equal(packageTitle("film-kit", ["A: x", "B: y"]), "Film kit");
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

describe("groupByPackage", () => {
  const all = [c("1", "Screenplay Studio: Cast", "ss"), c("2", "Screenplay Studio: Script", "ss"), c("3", "Featured"), c("4", "n8n: Failed", null, "int-1"), c("5", "Only: One", "solo")];

  test("folds a package's collections into one group", () => {
    const { groups } = groupByPackage(all);
    assert.equal(groups.length, 1);
    assert.deepEqual([groups[0].name, groups[0].items.map((x) => x.id)], ["Screenplay Studio", ["1", "2"]]);
  });
  test("keeps a person's collections, an integration's, and a package's lone collection in the plain list", () => {
    const { loose } = groupByPackage(all);
    assert.deepEqual(loose.map((x) => x.id).sort(), ["3", "4", "5"]);
  });
  test("an integration's collection is never grouped by package, even if it has one", () => {
    const { groups } = groupByPackage([c("1", "A: x", "p", "int"), c("2", "A: y", "p", "int")]);
    assert.equal(groups.length, 0);
  });
  test("groups are listed A to Z", () => {
    const { groups } = groupByPackage([c("1", "Zed: a", "z"), c("2", "Zed: b", "z"), c("3", "Alpha: a", "a"), c("4", "Alpha: b", "a")]);
    assert.deepEqual(groups.map((g) => g.name), ["Alpha", "Zed"]);
  });
});
