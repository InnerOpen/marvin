// Who the admin treats as a workspace admin (workspaceRole.ts). Run with `npm test`. The backend gate it
// mirrors is tested in tests/test_api_clients.py and tests/test_workspace_admin_gate.py.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { canManageWorkspace, nullIfForbidden } from "./workspaceRole.ts";

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
