// The API client permission list and the helpers behind the create/edit forms (apiClientPermissions.ts).
// Run with `npm test`. That the keys match what the backend enforces is checked in tests/test_api_clients.py.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  API_CLIENT_PERMISSIONS,
  initiallyGranted,
  PERMISSION_GROUPS,
  permissionsFromChecked,
  unlistedGrantedKeys,
} from "./apiClientPermissions.ts";

describe("API_CLIENT_PERMISSIONS", () => {
  test("test_permission_list_offers_form_submissions", () => {
    assert.ok(API_CLIENT_PERMISSIONS.some((p) => p.key === "write:form_submissions"));
  });

  test("test_permission_keys_are_unique_canonical_and_grouped", () => {
    const keys = API_CLIENT_PERMISSIONS.map((p) => p.key);
    assert.equal(new Set(keys).size, keys.length);
    for (const p of API_CLIENT_PERMISSIONS) {
      assert.match(p.key, /^(read|write):[a-z_]+$/);
      assert.ok(PERMISSION_GROUPS.includes(p.group), p.key);
    }
  });
});

describe("initiallyGranted", () => {
  test("test_initially_granted_for_new_client_returns_backend_defaults", () => {
    assert.deepEqual([...initiallyGranted()].sort(), ["read:assets", "read:collections", "read:published_entries"]);
  });

  test("test_initially_granted_for_existing_client_returns_only_true_keys", () => {
    const granted = initiallyGranted({ "read:assets": true, "write:form_submissions": false });
    assert.deepEqual([...granted], ["read:assets"]);
  });
});

describe("unlistedGrantedKeys", () => {
  test("test_unlisted_granted_keys_returns_legacy_grants_only", () => {
    const keys = unlistedGrantedKeys({ "read:assets": true, "read:draft_entries": true, "read:forms": false });
    assert.deepEqual(keys, ["read:draft_entries"]);
  });

  test("test_unlisted_granted_keys_with_no_permissions_returns_empty", () => {
    assert.deepEqual(unlistedGrantedKeys(null), []);
  });
});

describe("permissionsFromChecked", () => {
  test("test_permissions_from_checked_maps_each_key_to_true", () => {
    assert.deepEqual(permissionsFromChecked(["read:assets", "write:form_submissions", ""]), {
      "read:assets": true,
      "write:form_submissions": true,
    });
  });
});
