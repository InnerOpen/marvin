// "Apply a template" on the Entries page (applyTemplate.ts): which selections can take a template, and the preview in
// words. Run with `npm test` (plain `node --test`). Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { canConfirm, confirmLabel, doneLine, MAX_ENTRIES, previewLine, rowLine, selectionOf, templateSets, templateType } from "./applyTemplate.ts";

const ORNAMENT = {
  slug: "ornament",
  name: "Ornament",
  title: "{asset.name}",
  summary: "A hand-painted ornament",
  fields: { medium: "Acrylic and Ink on Ceramic", price: 85 },
  tags: ["ornaments"],
  assetField: "image",
};
const ARTWORK = templateType({
  id: "t-art",
  slug: "artwork",
  name: "Artwork",
  schemaJson: { fields: [{ key: "medium", label: "Medium", type: "text" }, { key: "price", type: "number" }, { key: "image", label: "Image", type: "asset" }] },
  templatesJson: [ORNAMENT],
});
const POST = templateType({ id: "t-post", slug: "post", name: "Post", schemaJson: { fields: [] }, templatesJson: null });
const TYPES = [ARTWORK, POST];
const pick = (id, entryTypeId) => ({ id, entryTypeId });
const PICTURE = { id: "a1", name: "Red cardinal", filename: "IMG_4491.jpeg" };

describe("templateType", () => {
  test("reads the fields and the templates, and survives a type with neither", () => {
    assert.equal(ARTWORK.templates.length, 1);
    assert.equal(ARTWORK.fields.length, 3);
    assert.deepEqual(POST.templates, []);
    assert.deepEqual(templateType({ id: "x", slug: "x" }).fields, []);
    assert.equal(templateType({ id: "x", slug: "note" }).name, "note");
  });
});

describe("selectionOf", () => {
  test("nothing picked", () => {
    assert.deepEqual(selectionOf([], TYPES), { kind: "none" });
  });

  test("entries of one type that has templates are ready", () => {
    const s = selectionOf([pick("a", "t-art"), pick("b", "t-art")], TYPES);
    assert.equal(s.kind, "ready");
    assert.equal(s.type.slug, "artwork");
  });

  test("entries of two types: a template belongs to one, the types are named, most entries first", () => {
    const s = selectionOf([pick("a", "t-post"), pick("b", "t-art"), pick("c", "t-art")], TYPES);
    assert.deepEqual(s, { kind: "mixed", names: ["Artwork", "Post"] });
  });

  test("a type with no templates says so", () => {
    const s = selectionOf([pick("a", "t-post")], TYPES);
    assert.equal(s.kind, "no-templates");
    assert.equal(s.type.name, "Post");
  });

  test("a type the page does not know is not offered a template", () => {
    assert.equal(selectionOf([pick("a", "t-gone")], TYPES).kind, "no-templates");
  });

  test("more than the API takes at once", () => {
    const many = Array.from({ length: MAX_ENTRIES + 1 }, (_, i) => pick(`e${i}`, "t-art"));
    assert.deepEqual(selectionOf(many, TYPES), { kind: "too-many", count: MAX_ENTRIES + 1 });
    assert.equal(selectionOf(many.slice(0, MAX_ENTRIES), TYPES).kind, "ready");
  });
});

describe("templateSets", () => {
  test("names what the template gives a value to, by the field's label; the title only with replace", () => {
    assert.deepEqual(templateSets(ORNAMENT, ARTWORK.fields, false), ["Summary", "Medium", "price", "Image"]);
    assert.deepEqual(templateSets(ORNAMENT, ARTWORK.fields, true), ["Title", "Summary", "Medium", "price", "Image"]);
  });

  test("a template with only tags sets no values", () => {
    assert.deepEqual(templateSets({ slug: "t", name: "T", tags: ["x"] }, [], false), []);
  });
});

describe("rowLine", () => {
  test("a fill names what is filled, what is kept, and what is added", () => {
    const row = { action: "fill", title: "Red cardinal", asset: PICTURE, changes: { fields: { price: 85, image: "a1" } }, tags: ["ornaments"], collections: ["shop", "gifts"], attach: true };
    assert.deepEqual(rowLine(row, ORNAMENT, ARTWORK.fields, false), {
      title: "Red cardinal",
      state: "fill",
      fills: ["price", "Image"],
      kept: ["Summary", "Medium"],
      adds: ["tag ornaments", "collections shop, gifts", "its picture, attached"],
      note: null,
    });
  });

  test("with replace the title is filled too", () => {
    const row = { action: "fill", title: "Red cardinal", asset: PICTURE, changes: { title: "Red cardinal", summary: "A hand-painted ornament", fields: { medium: "Acrylic and Ink on Ceramic" } } };
    const line = rowLine(row, ORNAMENT, ARTWORK.fields, true);
    assert.deepEqual(line.fills, ["Title", "Summary", "Medium"]);
    assert.deepEqual(line.kept, ["price", "Image"]);
  });

  test("an entry with no picture keeps nothing in the picture field: it is not named", () => {
    const line = rowLine({ action: "fill", title: "Wren", asset: null, changes: { fields: { medium: "Acrylic and Ink on Ceramic" } } }, ORNAMENT, ARTWORK.fields, false);
    assert.deepEqual(line.kept, ["Summary", "price"]);
  });

  test("a skipped entry carries the reason and nothing else", () => {
    const row = { action: "skip", title: "Blue jay", changes: {}, note: "it already has everything this template sets" };
    assert.deepEqual(rowLine(row, ORNAMENT, ARTWORK.fields, false), { title: "Blue jay", state: "skip", fills: [], kept: [], adds: [], note: "it already has everything this template sets" });
  });

  test("a row with an error is a problem, and the error is what it says", () => {
    const row = { action: "fill", title: "Owl", changes: { fields: { price: "lots" } }, note: "a note", error: "price: not a number" };
    const line = rowLine(row, ORNAMENT, ARTWORK.fields, false);
    assert.equal(line.state, "problem");
    assert.equal(line.note, "price: not a number");
  });

  test("a fill with no changes at all (only a tag) still reads", () => {
    const line = rowLine({ action: "fill", title: "Wren", changes: null, tags: ["ornaments"] }, ORNAMENT, ARTWORK.fields, false);
    assert.deepEqual(line.fills, []);
    assert.deepEqual(line.adds, ["tag ornaments"]);
  });
});

describe("the lines around the preview", () => {
  test("previewLine counts what would be filled and what is left", () => {
    assert.equal(previewLine({ total: 15, fill: 12, skip: 3, errors: 0 }, false), "12 of 15 entries would be filled, 3 left as they are.");
    assert.equal(previewLine({ total: 1, fill: 1, skip: 0, errors: 0 }, false), "1 of 1 entry would be filled.");
    assert.equal(previewLine({ total: 4, fill: 3, skip: 1, errors: 0 }, true), "3 of 4 entries would be changed, 1 left as it is.");
  });

  test("previewLine says when nothing would change, and when a problem stops it", () => {
    assert.equal(previewLine({ total: 3, fill: 0, skip: 3, errors: 0 }, false), "Nothing to do: all 3 entries are left as they are.");
    assert.equal(previewLine({ total: 1, fill: 0, skip: 1, errors: 0 }, false), "Nothing to do: the entry is left as it is.");
    assert.equal(previewLine({ total: 2, fill: 2, skip: 0, errors: 1 }, false), "2 of 2 entries would be filled. 1 has a problem: nothing is changed until it is fixed.");
  });

  test("confirmLabel says which of the two it does", () => {
    assert.equal(confirmLabel({ fill: 12 }, false), "Fill empty fields in 12 entries");
    assert.equal(confirmLabel({ fill: 1 }, true), "Replace values in 1 entry");
    assert.equal(confirmLabel(null, false), "Fill empty fields");
    assert.equal(confirmLabel({ fill: 0 }, true), "Replace values");
  });

  test("canConfirm needs something to do and no problem", () => {
    assert.equal(canConfirm(null), false);
    assert.equal(canConfirm({ todo: 0, errors: 0 }), false);
    assert.equal(canConfirm({ todo: 2, errors: 1 }), false);
    assert.equal(canConfirm({ todo: 2, errors: 0 }), true);
  });

  test("doneLine says what happened", () => {
    assert.equal(doneLine({ updated: 12, skip: 3 }, false), "Filled 12 entries, left 3 as they are.");
    assert.equal(doneLine({ updated: 1, skip: 0 }, true), "Changed 1 entry.");
    assert.match(doneLine({ updated: 2, skip: 0, treatmentJob: "j1" }, false), /pictures are being treated/);
  });
});
