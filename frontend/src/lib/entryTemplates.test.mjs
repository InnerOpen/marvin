// Entry templates on the entry type page (entryTemplates.ts): the title preview and the form <-> template mapping.
// Run with `npm test` (plain `node --test`). Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  formFromTemplate,
  putTemplate,
  renderPattern,
  sampleValues,
  slugify,
  templateFromForm,
  unknownVariables,
  valueFields,
  variablesIn,
} from "./entryTemplates.ts";

const FIELDS = [
  { key: "medium", type: "text" },
  { key: "notes", type: "markdown" },
  { key: "year", type: "number" },
  { key: "framed", type: "boolean" },
  { key: "size", type: "select", options: ["small", "large"] },
  { key: "image", type: "asset" },
  { key: "gallery", type: "asset-list" },
  { key: "supplier", type: "resource" },
  { key: "extra", type: "json" },
];

const DAY = new Date(2026, 10, 3);

describe("variables", () => {
  test("are read trimmed, in order, as the server reads them", () => {
    assert.deepEqual(variablesIn("{asset.name} #{ n } on {date}"), ["asset.name", "n", "date"]);
  });

  test("unknown ones are listed once, and an empty {} is one", () => {
    assert.deepEqual(unknownVariables("{title} {asset.name} {title} {}"), ["title", ""]);
    assert.deepEqual(unknownVariables("{ asset.filename } {n}"), []);
  });
});

describe("renderPattern", () => {
  test("fills the variables from a picture", () => {
    const values = sampleValues({ name: "Heron", originalFilename: "DSC_1.jpg", filename: "abc.jpg" }, DAY);
    assert.equal(renderPattern("{asset.name} ({asset.filename}) #{n}, {date}", values), "Heron (DSC_1.jpg) #1, 2026-11-03");
  });

  test("leaves an unknown variable as written", () => {
    assert.equal(renderPattern("{asset.name}: {colour}", sampleValues(null, DAY)), "Snowy Owl: {colour}");
  });

  test("a picture with no name is named after its file, and no picture gives the made-up sample", () => {
    assert.equal(sampleValues({ name: "", originalFilename: null, filename: "x.png" }, DAY)["asset.name"], "x.png");
    assert.deepEqual(sampleValues(undefined, DAY), { "asset.name": "Snowy Owl", "asset.filename": "IMG_0042.jpg", n: 1, date: "2026-11-03" });
  });
});

test("slugify makes the page's slugs", () => {
  assert.equal(slugify("  Bird photo (RAW)! "), "bird-photo-raw");
  assert.equal(slugify("a_b  c--d"), "a-b-c-d");
});

test("valueFields leaves out asset, resource and json fields", () => {
  assert.deepEqual(valueFields(FIELDS).map((f) => f.key), ["medium", "notes", "year", "framed", "size"]);
});

describe("formFromTemplate", () => {
  test("a new template puts the picture in the first asset field, as an inbox entry, featured", () => {
    const form = formFromTemplate(null, FIELDS);
    assert.equal(form.assetField, "image");
    assert.equal(form.status, "inbox");
    assert.equal(form.assetRole, "featured");
    assert.equal(form.title, "{asset.name}");
  });

  test("a stored template's values become the inputs' text", () => {
    const form = formFromTemplate(
      { slug: "a", name: "A", fields: { year: 2024, framed: false, medium: "oil" }, tags: ["x", "y"], assetField: null },
      FIELDS,
    );
    assert.deepEqual(form.fields, { year: "2024", framed: "false", medium: "oil" });
    assert.equal(form.tags, "x, y");
    assert.equal(form.assetField, "");
  });
});

describe("templateFromForm", () => {
  const blank = () => formFromTemplate(null, FIELDS);

  test("leaves blanks out and types the values", () => {
    const form = { ...blank(), slug: " owls ", name: " Owls ", tags: "birds, , owls, birds", collections: ["wild"] };
    form.fields = { medium: " photo ", year: "2024", framed: "false", size: "", notes: "" };
    assert.deepEqual(templateFromForm(form, FIELDS), {
      slug: "owls",
      name: "Owls",
      description: null,
      title: "{asset.name}",
      summary: null,
      entryDescription: null,
      fields: { medium: "photo", year: 2024, framed: false },
      tags: ["birds", "owls"],
      collections: ["wild"],
      status: "inbox",
      assetRole: "featured",
      assetField: "image",
    });
  });

  test("a number with a variable, or not a number, goes as text for the server to check", () => {
    const form = { ...blank(), slug: "a", name: "A", fields: { year: "{n}" } };
    assert.equal(templateFromForm(form, FIELDS).fields.year, "{n}");
    form.fields.year = "soon";
    assert.equal(templateFromForm(form, FIELDS).fields.year, "soon");
  });

  test("keeps what the editor does not show, and round-trips a stored template", () => {
    const stored = {
      slug: "a",
      name: "A",
      description: "For owls",
      title: "{asset.name} #{n}",
      summary: "S",
      entryDescription: "D",
      fields: { size: "huge", framed: true, medium: ["oil", "ink"], extra: { k: 1 }, gone: "x" },
      tags: ["t"],
      collections: ["not-loaded"],
      status: "needs_review",
      assetRole: "hero",
      assetField: "gallery",
    };
    assert.deepEqual(templateFromForm(formFromTemplate(stored, FIELDS), FIELDS, stored), stored);
  });

  test("a picture preset and its treated picture's role round-trip; none leaves both out", () => {
    const stored = { slug: "a", name: "A", title: "{asset.name}", picturePreset: "ornament-look", treatedRole: "hero" };
    const form = formFromTemplate(stored, FIELDS);
    assert.equal(form.picturePreset, "ornament-look");
    assert.equal(form.treatedRole, "hero");
    const back = templateFromForm(form, FIELDS, stored);
    assert.equal(back.picturePreset, "ornament-look");
    assert.equal(back.treatedRole, "hero");
    assert.equal(templateFromForm({ ...form, treatedRole: " " }, FIELDS).treatedRole, "featured");
    const none = templateFromForm({ ...form, picturePreset: "" }, FIELDS);
    assert.equal("picturePreset" in none, false);
    assert.equal("treatedRole" in none, false);
  });

  test("a template as the server answers it (no preset, featured) opens with none picked and featured", () => {
    const form = formFromTemplate({ slug: "a", name: "A", picturePreset: null, treatedRole: null }, FIELDS);
    assert.equal(form.picturePreset, "");
    assert.equal(form.treatedRole, "featured");
    assert.equal(formFromTemplate(null, FIELDS).picturePreset, "");
  });

  test("an unknown status falls back to inbox", () => {
    assert.equal(templateFromForm({ ...blank(), slug: "a", name: "A", status: "published" }, FIELDS).status, "inbox");
  });
});

test("putTemplate replaces by slug or adds at the end", () => {
  const list = [{ slug: "a", name: "A" }, { slug: "b", name: "B" }];
  assert.deepEqual(putTemplate(list, { slug: "a2", name: "A2" }, "a").map((t) => t.slug), ["a2", "b"]);
  assert.deepEqual(putTemplate(list, { slug: "c", name: "C" }, null).map((t) => t.slug), ["a", "b", "c"]);
  assert.equal(list[0].slug, "a");
});
