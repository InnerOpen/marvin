// The Automation needs-a-look summary's pure bits (automationAttention.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { countBadge, dashboardLine } from "./automationAttention.ts";

describe("the dashboard line", () => {
  test("says how many, and links to the page the server named", () => {
    assert.deepEqual(dashboardLine(3, "/automation/incoming-webhooks?status=attention"), {
      text: "Automation needs a look (3)",
      href: "/automation/incoming-webhooks?status=attention",
    });
  });

  test("falls back to the Workflows page when no page came back", () => {
    assert.equal(dashboardLine(1, null)?.href, "/automation/workflows?status=attention");
  });

  test("is hidden when nothing needs a look", () => {
    assert.equal(dashboardLine(0, "/x"), null);
    assert.equal(dashboardLine(undefined, null), null);
  });
});

describe("the count beside the Automation tab", () => {
  test("blank for none, the number, then 99+", () => {
    assert.equal(countBadge(0), "");
    assert.equal(countBadge(null), "");
    assert.equal(countBadge(4), "4");
    assert.equal(countBadge(250), "99+");
  });
});
