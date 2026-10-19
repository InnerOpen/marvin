// Custom entry types must be editable on a phone (Jared, 2026-10-19: "Editing 'Custom Type' in Content Model is
// uneditable on the phone"). Checked in a 390px and 375px touch browser against a seeded custom type with long labels,
// a select, an asset-list field and a long description; these keep the rules that fixed it in place:
//  - the list was an eleven-column table scrolled sideways, Edit/Delete ~1000px out at 390px wide (now compact
//    icon / name / kind rows on a phone, tap a row to edit; df22ebd2's stacked cards were too tall);
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

  test("both tables are compact rows on a phone, not stacked cards (Jared, 2026-10-19: the cards were too tall)", () => {
    assert.equal([...page.matchAll(/<table class="table types">/g)].length, 2);
    assert.doesNotMatch(page, /table[^>]*\bstacks\b/);
    assert.doesNotMatch(page, /stack-lead|stack-hide/);
  });

  test("on a phone only the icon, name and kind columns are left; the rest is hidden", () => {
    const phone = page.match(/@media \(max-width: 640px\) \{([\s\S]*?)\n {2}\}\n/)?.[1] ?? "";
    assert.match(phone, /\.types \.col-wide,\s*\.types \.type-meta \{\s*display: none;/);
    // slug, fields and entries (and actions, custom table only) are .col-wide, in the header and each row: 3 + 4 columns x 2 cells
    assert.equal([...page.matchAll(/<(?:th|td) class="col-wide[ "]/g)].length, (3 + 4) * 2);
  });

  test("a desktop table has six short columns, not eleven: the rendering details are one line under the name (Jared, 2026-10-19)", () => {
    assert.doesNotMatch(page, /col-render/);
    for (const gone of ["Rendered", "Renderer", "Package", "Version", "Sort Order"]) {
      assert.doesNotMatch(page, new RegExp(`<th[^>]*>${gone}</th>`));
    }
    assert.equal([...page.matchAll(/<small class="type-meta">/g)].length, 2);
    assert.match(page, /Renders with \$\{renderer/);
    // Fields goes and the slug moves under the name below 1100px (a 1024px content box is ~700px)
    assert.match(page, /@media \(max-width: 1100px\) \{\s*\.types \.col-fields,\s*\.types \.col-slug \{\s*display: none;/);
    // a long slug is cut with an ellipsis rather than broken letter by letter
    assert.match(page, /\.types td \.slug \{[^}]*text-overflow: ellipsis;/);
  });

  test("a custom type's name is a real link to its editor, stretched over the row, with a visible focus ring", () => {
    assert.equal([...page.matchAll(/<a class="row-link" href=\{`\/workspace\/entry-types\/\$\{type\.id\}`\}>/g)].length, 1);
    assert.match(page, /\.types \.row-link::after \{\s*content: "";\s*position: absolute;\s*inset: 0;/);
    assert.match(page, /\.types tr \{\s*position: relative;/);
    assert.match(page, /\.types \.row-link:focus-visible::after \{\s*outline:/);
  });

  test("the desktop Edit / Delete buttons stay (above the stretched link) and never wrap onto separate lines", () => {
    assert.match(page, /\.types \.actions \{\s*position: relative;/);
    assert.match(page, /\.types \.actions \{\s*flex-wrap: nowrap;\s*white-space: nowrap;/);
    assert.match(page, /action=\{`\/api\/entry-types\/\$\{type\.id\}\/delete`\}/);
  });
});

describe("entry type edit page", () => {
  const edit = read("pages/workspace/entry-types/[id].astro");

  test("a custom type can be deleted from here (the list rows just open this page on a phone), in its own form", () => {
    assert.match(edit, /\{canManage && !isSystem && \(\s*<form method="POST" action=\{`\/api\/entry-types\/\$\{id\}\/delete`\}/);
    assert.match(edit, /onclick="return confirm\('Delete this entry type\?'\)"/);
    // forms cannot nest: the delete form comes after the update form closes
    assert.ok(edit.indexOf("</form>") < edit.indexOf("/delete`"));
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
