// Who the admin treats as a workspace admin, editor or author (workspaceRole.ts). Run with `npm test`. The backend gate it
// mirrors is tested in tests/test_api_clients.py and tests/test_workspace_admin_gate.py.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  canAuthorContent,
  canEditContent,
  canEditEntry,
  canManageWorkspace,
  isForbidden,
  nullIfForbidden,
} from "./workspaceRole.ts";

const active = (role) => [
  { role: "OWNER", isActive: false },
  { role, isActive: true },
];

describe("canManageWorkspace", () => {
  for (const role of ["OWNER", "ADMIN"]) {
    test(`active workspace ${role} can manage`, () => {
      assert.equal(canManageWorkspace(active(role)), true);
    });
  }

  for (const role of ["EDITOR", "AUTHOR", "VIEWER"]) {
    test(`active workspace ${role} cannot manage, even if OWNER elsewhere`, () => {
      assert.equal(canManageWorkspace(active(role)), false);
    });
  }

  test("no active membership cannot manage", () => {
    assert.equal(canManageWorkspace([]), false);
  });

  test("platform super admin can manage without a membership", () => {
    assert.equal(canManageWorkspace([], { platformRole: "SUPER_ADMIN" }), true);
  });

  test("legacy admin flag can manage", () => {
    assert.equal(canManageWorkspace(active("VIEWER"), { admin: true }), true);
  });
});

describe("canEditContent / canAuthorContent", () => {
  const cases = { OWNER: [true, true], ADMIN: [true, true], EDITOR: [true, true], AUTHOR: [false, true], VIEWER: [false, false] };
  for (const [role, [edit, author]] of Object.entries(cases)) {
    test(`${role}: edit ${edit}, author ${author}`, () => {
      assert.equal(canEditContent(active(role)), edit);
      assert.equal(canAuthorContent(active(role)), author);
    });
  }

  test("no active membership can do neither; a super admin can do both", () => {
    assert.equal(canAuthorContent([]), false);
    assert.equal(canEditContent([], { platformRole: "SUPER_ADMIN" }), true);
  });
});

describe("canEditEntry", () => {
  const me = { id: "u1" };
  const mine = (status) => ({ createdBy: "u1", status });

  test("an EDITOR edits anyone's entry, published or not", () => {
    assert.equal(canEditEntry(active("EDITOR"), me, { createdBy: "u2", status: "published" }), true);
  });

  test("an AUTHOR edits their own entry until it is approved or published", () => {
    for (const status of ["inbox", "draft", "needs_review", "archived"]) {
      assert.equal(canEditEntry(active("AUTHOR"), me, mine(status)), true, status);
    }
    for (const status of ["approved", "published"]) {
      assert.equal(canEditEntry(active("AUTHOR"), me, mine(status)), false, status);
    }
  });

  test("an AUTHOR cannot edit someone else's entry; a VIEWER cannot edit their own", () => {
    assert.equal(canEditEntry(active("AUTHOR"), me, { createdBy: "u2", status: "draft" }), false);
    assert.equal(canEditEntry(active("VIEWER"), me, mine("draft")), false);
  });
});

describe("nullIfForbidden", () => {
  test("passes a successful result through", async () => {
    assert.deepEqual(await nullIfForbidden(Promise.resolve([1])), [1]);
  });

  test("turns a 403 into null", async () => {
    assert.equal(await nullIfForbidden(Promise.reject({ statusCode: 403 })), null);
  });

  test("rethrows any other failure", async () => {
    await assert.rejects(nullIfForbidden(Promise.reject({ status: 500 })), { status: 500 });
  });
});

describe("isForbidden", () => {
  test("a 403 from the SDK (statusCode) or fetch (status) is forbidden", () => {
    assert.equal(isForbidden({ statusCode: 403 }), true);
    assert.equal(isForbidden({ status: 403 }), true);
  });

  test("anything else is not", () => {
    for (const e of [{ status: 404 }, { statusCode: 500 }, new Error("boom"), null, undefined]) {
      assert.equal(isForbidden(e), false);
    }
  });
});
