// Custom entry types must be editable on a phone (Jared, 2026-10-19: "Editing 'Custom Type' in Content Model is
// uneditable on the phone"). Checked in a 390px and 375px touch browser against a seeded custom type with long labels,
// a select, an asset-list field and a long description; these keep the rules that fixed it in place:
//  - the list was an eleven-column table scrolled sideways, Edit/Delete ~1000px out at 390px wide;
//  - in the schema editor a long field label pushed the card's header wider than the card (which clips), so the
//    move / Remove buttons were unreachable, and the two-column body left ~130px inputs;
//  - a field type the picker does not offer (asset-list) fell back to Text and was saved as text on the next edit.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

const SRC = new URL("../", import.meta.url);
const read = (path) => readFileSync(new URL(path, SRC), "utf8");

describe("entry types list", () => {
  const page = read("pages/workspace/entry-types.astro");

  test("both tables stack into cards on a phone, so Edit is in reach", () => {
    assert.equal([...page.matchAll(/<table class="table stacks types">/g)].length, 2);
    assert.match(read("styles/global.css"), /@media \(max-width: 640px\)\s*\{\s*\.table\.stacks,/);
  });

  test("the card keeps the icon, name, kind, slug, count and actions; the rendering columns are dropped", () => {
    assert.equal([...page.matchAll(/<td class="stack-lead">/g)].length, 2);
    assert.equal([...page.matchAll(/<td class="action">/g)].length, 1);
    assert.equal([...page.matchAll(/<td class="stack-hide">/g)].length, 10);
  });
});

describe("schema editor", () => {
  const editor = read("components/SchemaEditor.astro");
  const phone = editor.match(/@media \(max-width: 640px\) \{([\s\S]*?)\n {2}\}\n/)?.[1] ?? "";

  test("a long label wraps inside its card instead of widening it", () => {
    assert.match(
      editor,
      /\.field-editor-title,\s*\.schema-editor \.field-editor-body > \* \{\s*min-width: 0;\s*overflow-wrap: anywhere;/,
    );
  });

  test("on a phone the header stacks, the body is one column, inputs are 16px (no iOS zoom) and buttons tap-sized", () => {
    assert.match(phone, /\.field-editor-header \{\s*flex-direction: column;/);
    assert.match(phone, /\.field-editor-body \{\s*grid-template-columns: minmax\(0, 1fr\);/);
    assert.match(phone, /font-size: 16px;/);
    assert.match(phone, /\.field-editor-actions button \{\s*min-height: 44px;/);
  });

  test("a field type outside the picker stays selected as itself", () => {
    assert.match(editor, /typeInfo\.value \? \[\] : \[new Option\(field\.type, field\.type, true, true\)\]/);
  });
});

describe("entry type forms", () => {
  for (const file of ["pages/workspace/entry-types/[id].astro", "pages/workspace/entry-types/new.astro"]) {
    test(`${file}: tighter padding and 16px inputs on a phone`, () => {
      const page = read(file);
      assert.match(page, /@media \(max-width: 640px\) \{\s*\.form \{ padding: 1rem; \}/);
      assert.match(page, /select \{ font-size: 16px; \}/);
    });
  }

  test("the hidden submission-settings box really hides", () => {
    assert.match(read("pages/workspace/entry-types/[id].astro"), /\.submission-settings\[hidden\] \{\s*display: none;/);
  });
});
