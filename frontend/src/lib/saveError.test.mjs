// What a failed save's banner says (saveError.ts). Run with `npm test` — plain `node --test`, which
// strips the .ts types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { describeSaveError } from "./saveError.ts";

/** What the SDK throws for a non-2xx answer: the body is kept as the raw JSON string. */
function sdkError(status, body) {
  const error = new Error(
    `Marvin API error: ${status} Unprocessable Entity at /api/platform/entries/1\n${JSON.stringify(body)}`,
  );
  error.statusCode = status;
  error.responseBody = JSON.stringify(body);
  return error;
}

describe("describeSaveError", () => {
  test("lists each issue the publish gate refused with", () => {
    const error = sdkError(422, {
      detail: {
        message: "Cannot publish — 2 requirement(s) unmet.",
        issues: [
          "Required field 'Subject' is empty.",
          "The expiration date (Oct 1, 2026 14:05 UTC) has passed — clear it or set a later date.",
        ],
      },
    });

    assert.deepEqual(describeSaveError(error), {
      message: "Cannot publish — 2 requirement(s) unmet.",
      issues: [
        "Required field 'Subject' is empty.",
        "The expiration date (Oct 1, 2026 14:05 UTC) has passed — clear it or set a later date.",
      ],
    });
  });

  test("shows a plain string detail as the message", () => {
    const error = sdkError(409, { detail: "An entry with this slug already exists." });

    assert.deepEqual(describeSaveError(error), { message: "An entry with this slug already exists.", issues: [] });
  });

  test("lists request validation errors by field", () => {
    const error = sdkError(422, {
      detail: [
        { loc: ["body", "status"], msg: "Value error, status must be one of: draft, published", type: "value_error" },
      ],
    });

    assert.deepEqual(describeSaveError(error), {
      message: "Some fields aren't valid.",
      issues: ["status: Value error, status must be one of: draft, published"],
    });
  });

  test("reads fetchApi's already-parsed body too", () => {
    const error = Object.assign(new Error("x"), { status: 422, body: { detail: { message: "Nope", issues: ["A"] } } });

    assert.deepEqual(describeSaveError(error), { message: "Nope", issues: ["A"] });
  });

  test("says to sign in again on an auth failure", () => {
    const error = Object.assign(new Error("Authentication failed: Unauthorized"), { statusCode: 401 });

    assert.match(describeSaveError(error).message, /Sign in again/);
  });

  test("keeps only the first line of an SDK message with no readable body", () => {
    const error = new Error("Marvin API error: 400 Bad Request at /api/platform/entries/1\n<html>oops</html>");
    error.responseBody = "<html>oops</html>";

    assert.deepEqual(describeSaveError(error), {
      message: "Marvin API error: 400 Bad Request at /api/platform/entries/1",
      issues: [],
    });
  });

  test("falls back to a generic message for something that isn't an error", () => {
    assert.deepEqual(describeSaveError(undefined), { message: "Couldn't save your changes.", issues: [] });
  });
});
