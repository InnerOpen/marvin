// Why an entry needs review (reviewReasons.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { integrationErrors, reviewReasons } from "./reviewReasons.ts";

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

describe("integrationErrors", () => {
  test("names the provider, the error code and its message", () => {
    const metadata = {
      integration_error: { shop: { provider_name: "Square", code: "invalid", message: "price must be positive" } },
    };

    assert.deepEqual(integrationErrors(metadata), ["Square · invalid — price must be positive"]);
  });

  test("falls back to the connection's slug and skips empty notes", () => {
    assert.deepEqual(integrationErrors({ integration_error: { news: { code: "blocked" }, junk: {}, bad: "x" } }), [
      "news · blocked",
    ]);
  });

  test("are listed after the other review reasons", () => {
    const metadata = {
      review_reasons: ["flagged"],
      integration_error: { shop: { provider_name: "Square", code: "auth" } },
    };

    assert.deepEqual(reviewReasons(metadata), ["flagged", "Square · auth"]);
  });
});
