// Why an entry needs review (reviewReasons.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { reviewReasons } from "./reviewReasons.ts";

describe("reviewReasons", () => {
  test("lists a flagged submission's reasons, then a workflow's", () => {
    const metadata = {
      submission: { received_at: "2026-10-04T10:00:00Z", review_reasons: ["disposable email domain"] },
      review_reasons: ["Buttondown refused the signup: blocked"],
    };

    assert.deepEqual(reviewReasons(metadata), ["disposable email domain", "Buttondown refused the signup: blocked"]);
  });

  test("lists a reason given twice once", () => {
    assert.deepEqual(reviewReasons({ submission: { review_reasons: ["x"] }, review_reasons: ["x"] }), ["x"]);
  });

  test("ignores blanks and anything that isn't text", () => {
    assert.deepEqual(reviewReasons({ review_reasons: ["", 3, null, "kept"] }), ["kept"]);
  });

  test("an entry with no metadata has no reasons", () => {
    assert.deepEqual(reviewReasons(null), []);
    assert.deepEqual(reviewReasons({ submission: "odd", review_reasons: "not a list" }), []);
  });
});
