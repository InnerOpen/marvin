// A character's sheet fields (characterSheet.ts): bubble lines and mood settings as HTML, and the lines a
// textarea holds. Run with `npm test`. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { linesFieldsHtml, linesOf, moodFieldsHtml } from "./characterSheet.ts";

describe("characterSheet", () => {
  test("test_lines_of_a_textarea_drop_blank_rows_and_trim", () => {
    assert.deepEqual(linesOf("  Well, hello.  \n\n *flips hair*\n"), ["Well, hello.", "*flips hair*"]);
  });

  test("test_lines_fields_escape_what_they_show", () => {
    const html = linesFieldsHtml({ greetings: ['<b>"hi"</b>'] }, { taglines: ["a & b"] });
    assert.ok(html.includes("&lt;b&gt;&quot;hi&quot;&lt;/b&gt;") && html.includes('placeholder="a &amp; b"'));
    assert.ok(!html.includes("<b>"));
  });

  test("test_mood_fields_show_the_saved_choices_and_open_only_when_something_is_set", () => {
    assert.ok(!moodFieldsHtml(null).includes('<details class="mood-fields" open'));
    const html = moodFieldsHtml({ drains: "treatment", low: { greetings: ["Mm-hmm."] } });
    assert.ok(html.includes('<details class="mood-fields" open'));
    assert.ok(html.includes('value="treatment" selected') && html.includes("Mm-hmm."));
    assert.ok(html.includes("the Social Battery"));
  });
});
