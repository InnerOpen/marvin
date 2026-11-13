import assert from "node:assert/strict";
import { test } from "node:test";
import { approvalsPath } from "./approvalFilters.ts";

test("with nothing to narrow by, the waiting list is asked for plainly", () => {
  assert.equal(approvalsPath("pending"), "/api/automations/approvals");
  assert.equal(approvalsPath("decided"), "/api/automations/approvals?state=decided");
});

test("a page asks for its own cards: one workflow, some entries, one run", () => {
  assert.equal(approvalsPath("pending", { automation: "make-stills" }), "/api/automations/approvals?automation=make-stills");
  assert.equal(
    approvalsPath("decided", { automation: "keep takes", entryIds: ["a", "b"], executionId: "run-1" }),
    "/api/automations/approvals?state=decided&automation=keep+takes&entry_id=a&entry_id=b&execution_id=run-1",
  );
});

test("more entries than one request may name are left out rather than refused", () => {
  const many = Array.from({ length: 60 }, (_, i) => `e${i}`);
  assert.equal(new URLSearchParams(approvalsPath("pending", { entryIds: many }).split("?")[1]).getAll("entry_id").length, 50);
});
