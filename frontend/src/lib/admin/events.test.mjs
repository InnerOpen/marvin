// Platform admin Events page helpers (events.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { apiQuery, formatUtc, groupTypesByCategory, hasFilters, pageHref, parseFilters, rangeLabel } from "./events.ts";

const WS = "3f2b9c1e-8a4d-4e6f-9b0a-1c2d3e4f5a6b";

describe("parseFilters", () => {
  test("reads the page's query string", () => {
    const f = parseFilters(
      new URLSearchParams(`type=user_signup&workspace=${WS}&from=2026-10-01&to=2026-10-05&page=3`),
    );
    assert.deepEqual(f, { eventType: "user_signup", workspaceId: WS, from: "2026-10-01", to: "2026-10-05", page: 3 });
  });

  test("drops anything malformed instead of passing it on", () => {
    const f = parseFilters(new URLSearchParams("type=<b>x</b>&workspace=nope&from=2026-02-30&to=yesterday&page=-2"));
    assert.deepEqual(f, { eventType: "", workspaceId: "", from: "", to: "", page: 1 });
  });

  test("an empty query is no filters, page 1", () => {
    const f = parseFilters(new URLSearchParams(""));
    assert.equal(hasFilters(f), false);
    assert.equal(f.page, 1);
  });
});

describe("apiQuery", () => {
  test("turns the days into an inclusive UTC range", () => {
    const q = new URLSearchParams(
      apiQuery({ eventType: "workspace_created", workspaceId: WS, from: "2026-10-01", to: "2026-10-05", page: 2 }),
    );
    assert.equal(q.get("event_type"), "workspace_created");
    assert.equal(q.get("workspace_id"), WS);
    assert.equal(q.get("start_date"), "2026-10-01T00:00:00Z");
    assert.equal(q.get("end_date"), "2026-10-05T23:59:59.999Z");
    assert.equal(q.get("page"), "2");
    assert.equal(q.get("per_page"), "50");
  });

  test("leaves unset filters out", () => {
    assert.equal(apiQuery({ eventType: "", workspaceId: "", from: "", to: "", page: 1 }, 25), "page=1&per_page=25");
  });
});

describe("pageHref", () => {
  const f = { eventType: "user_signup", workspaceId: "", from: "2026-10-01", to: "", page: 1 };

  test("keeps the filters on another page", () => {
    assert.equal(pageHref(f, 2), "/admin/events?type=user_signup&from=2026-10-01&page=2");
  });

  test("page 1 has no page parameter", () => {
    assert.equal(pageHref(f, 1), "/admin/events?type=user_signup&from=2026-10-01");
    assert.equal(pageHref({ ...f, eventType: "", from: "" }, 1), "/admin/events");
  });
});

describe("display", () => {
  test("formatUtc", () => {
    assert.equal(formatUtc("2026-10-05T14:03:27.123456+00:00"), "2026-10-05 14:03 UTC");
    assert.equal(formatUtc("2026-10-05T10:03:00-04:00"), "2026-10-05 14:03 UTC");
    assert.equal(formatUtc(null), "—");
    assert.equal(formatUtc("not a date"), "—");
  });

  test("groupTypesByCategory keeps the API's order", () => {
    const t = (eventType, category) => ({ eventType, name: eventType, description: "", category });
    const groups = groupTypesByCategory([
      t("user_signup", "Authentication"),
      t("workspace_created", "Workspaces"),
      t("token_refreshed", "Authentication"),
    ]);
    assert.deepEqual(
      groups.map((g) => [g.category, g.types.map((x) => x.eventType)]),
      [
        ["Authentication", ["user_signup", "token_refreshed"]],
        ["Workspaces", ["workspace_created"]],
      ],
    );
  });

  test("rangeLabel", () => {
    const items = (n) => Array.from({ length: n }, () => ({}));
    assert.equal(
      rangeLabel({ page: 2, per_page: 50, total: 120, total_pages: 3, items: items(50) }),
      "Showing 51–100 of 120",
    );
    assert.equal(
      rangeLabel({ page: 3, per_page: 50, total: 120, total_pages: 3, items: items(20) }),
      "Showing 101–120 of 120",
    );
    assert.equal(rangeLabel({ page: 1, per_page: 50, total: 0, total_pages: 0, items: [] }), "No events");
  });
});
