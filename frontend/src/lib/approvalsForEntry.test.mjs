// Which approvals a banner shows on an entry (approvalsForEntry.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { pendingFor } from "./approvalsForEntry.ts";

const a = (id, entryId, status = "pending") => ({ id, entryId, status, message: id, automationId: "w", approvers: "editor", expiresAt: "2026-12-01T00:00:00Z" });

describe("pendingFor", () => {
  test("only the pending approvals of that entry", () => {
    const list = [a("1", "e1"), a("2", "e2"), a("3", "e1", "approved"), a("4", "e1")];
    assert.deepEqual(pendingFor(list, "e1").map((x) => x.id), ["1", "4"]);
  });
  test("nothing for an unknown or missing entry", () => {
    assert.deepEqual(pendingFor([a("1", "e1")], "e9"), []);
    assert.deepEqual(pendingFor([a("1", "e1")], undefined), []);
    assert.deepEqual(pendingFor([a("1", null)], null), []);
  });
});
