// Pages that need a workspace, and where a user with none lands (workspaceGate.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { isNoWorkspaceError, needsWorkspace, noWorkspaceLanding } from "./workspaceGate.ts";

describe("needsWorkspace", () => {
  test("the dashboard and the workspace's pages need one", () => {
    for (const path of ["/", "/workspace", "/workspace/entries/1", "/automation/workflows", "/publishing/site", "/workspaces", "/share"]) {
      assert.equal(needsWorkspace(path), true, path);
    }
  });

  test("Admin, sign-in, the waiting page and the profile do not", () => {
    for (const path of ["/admin", "/admin/workspaces", "/admin/users/1", "/login", "/register", "/no-workspace", "/user/profile"]) {
      assert.equal(needsWorkspace(path), false, path);
    }
  });

  test("a prefix only matches a whole path segment", () => {
    assert.equal(needsWorkspace("/workspaces-old"), false);
    assert.equal(needsWorkspace("/sharepoint"), false);
  });
});

describe("noWorkspaceLanding", () => {
  test("a super admin goes to Admin, anyone else to the waiting page", () => {
    assert.equal(noWorkspaceLanding("SUPER_ADMIN"), "/admin");
    assert.equal(noWorkspaceLanding("NONE"), "/no-workspace");
    assert.equal(noWorkspaceLanding(undefined), "/no-workspace");
  });
});

describe("isNoWorkspaceError", () => {
  test("recognises the API's 409 body only", () => {
    assert.equal(isNoWorkspaceError({ detail: { code: "no_workspace", message: "x" } }), true);
    assert.equal(isNoWorkspaceError({ detail: "no_workspace" }), false);
    assert.equal(isNoWorkspaceError({ detail: { code: "other" } }), false);
    assert.equal(isNoWorkspaceError(null), false);
  });
});
