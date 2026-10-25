// The Workflows page's list (workflowList.ts): how a workflow starts, its one-line summary, and the adapter that
// feeds the shared list kit. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { organize, statusOptions } from "./organizedList.ts";
import {
  attentionHtml,
  editedHtml,
  attentionReason,
  humanInterval,
  STARTS_OPTIONS,
  triggerKind,
  triggerSummary,
  workflowAdapter,
  workflowCardHtml,
} from "./workflowList.ts";

const wf = (trigger, extra = {}) => ({
  id: "x",
  name: "X",
  enabled: true,
  definition: { trigger },
  ...extra,
});
const names = {
  webhookName: (ref) => (ref === "hook" ? "Deploy hook" : ref),
  automationName: (ref) => (ref === "a" ? "Nightly" : ref),
};

describe("how a workflow starts", () => {
  test("kinds: events, schedule, webhook, by hand", () => {
    assert.equal(
      triggerKind(wf({ type: "event", event: "entry_published" })),
      "event",
    );
    assert.equal(
      triggerKind(wf({ type: "chained", automation: "a" })),
      "event",
    );
    assert.equal(triggerKind(wf({ type: "on_error" })), "event");
    assert.equal(triggerKind(wf({ type: "schedule" })), "schedule");
    assert.equal(triggerKind(wf({ type: "incoming_webhook" })), "webhook");
    assert.equal(triggerKind(wf({ type: "manual" })), "manual");
    assert.equal(triggerKind(wf({ type: "mcp" })), "manual");
  });

  test("a workflow with no trigger counts as an event workflow", () => {
    assert.equal(triggerKind({ id: "x", name: "X", enabled: true }), "event");
  });

  test("the Starts filter offers the four ways", () => {
    assert.deepEqual(
      STARTS_OPTIONS.map((o) => o.value),
      ["event", "schedule", "webhook", "manual"],
    );
  });

  test("summaries read like the cards always did", () => {
    assert.equal(triggerSummary(wf({ type: "manual" }), names), "run manually");
    assert.equal(triggerSummary(wf({ type: "mcp" }), names), "MCP tool");
    assert.equal(
      triggerSummary(wf({ type: "event", event: "entry_published" }), names),
      "entry published",
    );
    assert.equal(
      triggerSummary(
        wf({ type: "schedule", schedule_config: { interval_seconds: 86400 } }),
        names,
      ),
      "every 1 day",
    );
    assert.equal(
      triggerSummary(wf({ type: "chained", automation: "a" }), names),
      "after Nightly",
    );
    assert.equal(
      triggerSummary(wf({ type: "on_error", automation: "a" }), names),
      "if Nightly fails",
    );
    assert.equal(
      triggerSummary(wf({ type: "incoming_webhook", webhook: "hook" }), names),
      "Deploy hook received",
    );
  });

  test("intervals", () => {
    assert.equal(humanInterval(120), "2 minutes");
    assert.equal(humanInterval(3600), "1 hour");
    assert.equal(humanInterval(0), "—");
  });
});

describe("the workflow adapter", () => {
  const adapter = workflowAdapter(names);
  const items = [
    wf(
      { type: "event", event: "bench_note_published" },
      { id: "1", name: "Tell Slack" },
    ),
    wf(
      { type: "schedule", schedule_config: { interval_seconds: 3600 } },
      { id: "2", name: "Hourly", sourceIntegrationId: "b1" },
    ),
    wf(
      { type: "manual" },
      { id: "3", name: "Mine", sourceRecipe: "r", enabled: false },
    ),
  ];

  test("reads camelCase source fields from the API", () => {
    assert.deepEqual(adapter.source(items[1]), {
      integrationId: "b1",
      blueprint: null,
      recipe: null,
    });
    assert.deepEqual(adapter.source(items[2]), {
      integrationId: null,
      blueprint: null,
      recipe: "r",
    });
  });

  test("search finds a workflow by what starts it", () => {
    const hit = organize(
      items,
      adapter,
      {},
      {},
      { query: "bench note published" },
    );
    assert.deepEqual(
      hit.sections.flatMap((s) => s.items.map((i) => i.id)),
      ["1"],
    );
  });

  test("the Starts filter uses the trigger kind", () => {
    const hit = organize(
      items,
      adapter,
      { b1: { name: "B" } },
      { starts: "schedule" },
    );
    assert.deepEqual(
      hit.sections.flatMap((s) => s.items.map((i) => i.id)),
      ["2"],
    );
  });

  test("Needs attention matches the flagged workflows, and the Status filter offers it", () => {
    const flagged = [
      wf({ type: "manual" }, { id: "1", attention: "last_run_failed" }),
      wf({ type: "manual" }, { id: "2", attention: null }),
      wf({ type: "manual" }, { id: "3" }),
      wf(
        { type: "manual" },
        { id: "4", enabled: false, attention: "off_while_integration_on" },
      ),
    ];
    const hit = organize(flagged, adapter, {}, { status: "attention" });
    assert.deepEqual(
      hit.sections.flatMap((s) => s.items.map((i) => i.id)).sort(),
      ["1", "4"],
    );
    assert.equal(
      statusOptions({ attention: true })[0].label,
      "Needs attention",
    );
  });
});

describe("the card", () => {
  const card = (extra = {}) =>
    workflowCardHtml(
      wf({ type: "manual" }, { id: "7", name: 'A "b" <c>', ...extra }),
      {
        summary: "run manually",
        details: "<p>flow</p>",
        linked: false,
      },
    );

  test("Run and Edit are on the card; the rest sit in the ⋯ menu", () => {
    const html = card();
    const [outside, menu] = html.split('<div class="org-menu"');
    assert.match(outside, /js-run/);
    assert.match(outside, /js-edit/);
    for (const cls of ["js-dryrun", "js-history", "js-copy", "js-delete"])
      assert.match(menu, new RegExp(cls));
  });

  test("escapes the name; carries the id, the trigger and the steps", () => {
    const html = card();
    assert.match(html, /data-id="7"/);
    assert.match(html, /A &quot;b&quot; &lt;c&gt;/);
    assert.match(html, /run manually/);
    assert.match(html, /<p>flow<\/p>/);
  });

  test("an off workflow is dimmed, says Off, and can't be run", () => {
    const html = card({ enabled: false });
    assert.match(html, /class="org-card wf-card off"/);
    assert.match(html, /Off · run manually/);
    assert.match(html, /js-run" disabled/);
  });

  test("the linked workflow is marked", () => {
    assert.match(
      workflowCardHtml(wf({ type: "manual" }), {
        summary: "",
        details: "",
        linked: true,
      }),
      /wf-card linked/,
    );
  });

  describe("the last run", () => {
    const NOW = new Date("2026-10-21T12:00:00Z");
    const last = (lastRunAt, lastRunStatus) =>
      workflowCardHtml(wf({ type: "manual" }, { lastRunAt, lastRunStatus }), {
        summary: "run manually",
        details: "",
        linked: false,
        now: NOW,
      });
    const line = (html) =>
      html.match(/<div class="wf-last[^"]*"[^>]*>(.*?)<\/div>/)?.[0] ?? "";

    test("says when it ran and how it went", () => {
      assert.match(
        line(last("2026-10-21T10:00:00Z", "success")),
        /Last run 2 h ago · succeeded/,
      );
    });

    test("a failed run is marked", () => {
      const html = line(last("2026-10-21T10:00:00Z", "failed"));
      assert.match(html, /Last run 2 h ago · failed/);
      assert.match(html, /class="wf-last failed"/);
    });

    test("a partly failed run is marked too, a good one is not", () => {
      assert.match(
        line(last("2026-10-21T11:00:00Z", "partial")),
        /wf-last failed.*partly failed/,
      );
      assert.doesNotMatch(
        line(last("2026-10-21T11:00:00Z", "success")),
        /failed/,
      );
    });

    test("running and cancelled read plainly", () => {
      assert.match(
        line(last("2026-10-21T11:58:00Z", "running")),
        /Last run 2 min ago · running/,
      );
      assert.match(
        line(last("2026-10-21T11:00:00Z", "cancelled")),
        /1 h ago · cancelled/,
      );
    });

    test("never run: says so, no outcome", () => {
      assert.match(line(last(null, null)), /Not run yet/);
      assert.doesNotMatch(line(last(undefined, undefined)), /Last run/);
    });

    test("an unknown status is shown as it came, escaped", () => {
      assert.match(
        line(last("2026-10-21T10:00:00Z", "<odd>")),
        /· &lt;odd&gt;/,
      );
    });

    test("a mark reads at a glance: ✓ for success, ✕ for a failure", () => {
      assert.match(
        line(last("2026-10-21T10:00:00Z", "success")),
        /class="wf-last ok".*✓/,
      );
      assert.match(
        line(last("2026-10-21T10:00:00Z", "failed")),
        /class="wf-last failed".*✕/,
      );
    });

    test("failures earlier in the week show even when the last run went fine", () => {
      const html = workflowCardHtml(
        wf(
          { type: "manual" },
          {
            lastRunAt: "2026-10-21T10:00:00Z",
            lastRunStatus: "success",
            failedRuns7d: 3,
          },
        ),
        {
          summary: "",
          details: "",
          linked: false,
          now: NOW,
        },
      );
      assert.match(
        line(html),
        /succeeded · <span class="wf-week-failed">3 failed this week<\/span>/,
      );
      assert.match(html, /Needs a look.*3 runs failed this week/);
    });
  });
});

describe("the Needs a look marker", () => {
  test("failed runs this week flag a workflow for Needs attention, as the dashboard counts them", () => {
    const adapter = workflowAdapter({
      webhookName: (x) => x,
      automationName: (x) => x,
    });
    assert.equal(adapter.attention(wf({}, { failedRuns7d: 2 })), true);
    assert.equal(adapter.attention(wf({}, { failedRuns7d: 0 })), false);
    assert.equal(
      attentionReason(wf({}, { failedRuns7d: 1 })),
      "1 run failed this week",
    );
    assert.equal(
      attentionReason(
        wf({}, { attention: "last_run_failed", failedRuns7d: 4 }),
      ),
      "The last run failed",
    );
  });

  test("a flagged card says why; an unflagged one has no marker", () => {
    assert.match(
      attentionHtml(wf({}, { attention: "last_run_failed" })),
      /Needs a look.*The last run failed/,
    );
    assert.match(
      attentionHtml(wf({}, { attention: "off_while_integration_on" })),
      /Off, but its integration is on/,
    );
    assert.equal(attentionHtml(wf({}, { attention: null })), "");
    assert.equal(attentionHtml(wf({})), "");
    assert.equal(
      attentionReason(wf({}, { attention: "something_new" })),
      "Needs a look",
    );
  });

  test("the marker is on the card, and the reason is escaped", () => {
    const html = workflowCardHtml(
      wf({ type: "manual" }, { attention: "last_run_failed" }),
      {
        summary: "",
        details: "",
        linked: false,
      },
    );
    assert.match(html, /class="wf-attention"/);
    assert.doesNotMatch(
      workflowCardHtml(wf({ type: "manual" }), {
        summary: "",
        details: "",
        linked: false,
      }),
      /wf-attention/,
    );
  });
});

describe("the Edited tag", () => {
  test("only an integration workflow changed here carries it", () => {
    assert.match(
      editedHtml(wf({}, { editedSinceInstall: true })),
      /class="wf-edited".*>Edited</,
    );
    assert.equal(editedHtml(wf({}, { editedSinceInstall: false })), "");
    assert.equal(editedHtml(wf({})), "");
  });
});
