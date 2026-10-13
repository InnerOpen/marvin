// One-time API token display (tokenReveal.ts). Run with `npm test`. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { forgetToken, revealTokenOnce, TOKEN_VALUE_SELECTOR } from "./tokenReveal.ts";

/** A stand-in for the <dialog>: records whether it was opened and what the token slot holds. */
function fakeDialog({ hasSlot = true } = {}) {
  const slot = { textContent: "" };
  return {
    slot,
    opened: false,
    showModal() {
      this.opened = true;
    },
    close() {
      this.opened = false;
    },
    querySelector(selector) {
      return hasSlot && selector === TOKEN_VALUE_SELECTOR ? slot : null;
    },
  };
}

describe("revealTokenOnce", () => {
  test("test_reveal_with_token_fills_slot_and_opens_dialog", () => {
    const dialog = fakeDialog();

    const shown = revealTokenOnce(dialog, "mrv_abc123");

    assert.equal(shown, true);
    assert.equal(dialog.slot.textContent, "mrv_abc123");
    assert.equal(dialog.opened, true);
  });

  for (const missing of ["", null, undefined]) {
    test(`test_reveal_without_token_(${missing})_leaves_dialog_closed`, () => {
      const dialog = fakeDialog();

      assert.equal(revealTokenOnce(dialog, missing), false);
      assert.equal(dialog.opened, false);
    });
  }

  test("test_reveal_without_token_slot_leaves_dialog_closed", () => {
    const dialog = fakeDialog({ hasSlot: false });

    assert.equal(revealTokenOnce(dialog, "mrv_abc123"), false);
    assert.equal(dialog.opened, false);
  });
});

describe("forgetToken", () => {
  test("test_forget_after_reveal_clears_token_from_page", () => {
    const dialog = fakeDialog();
    revealTokenOnce(dialog, "mrv_abc123");

    forgetToken(dialog);

    assert.equal(dialog.slot.textContent, "");
  });
});
