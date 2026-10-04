// Collection form helpers (collectionForm.ts). Run with `npm test` — plain `node --test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { IS_PUBLIC_FIELD, isPublicFromForm } from "./collectionForm.ts";

describe("isPublicFromForm", () => {
  test("checked visibility toggle sends is_public true", () => {
    const form = new FormData();
    form.set(IS_PUBLIC_FIELD, "true");
    assert.equal(isPublicFromForm(form), true);
  });

  test("unchecked visibility toggle (field absent) sends is_public false", () => {
    assert.equal(isPublicFromForm(new FormData()), false);
  });
});
