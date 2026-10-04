// Activity toaster helpers (toast.ts). Run with `npm test` — plain `node --test`, which strips
// toast.ts's types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, mock, test } from "node:test";

import {
  approvalTarget,
  changeHref,
  changesLabel,
  dismissTimer,
  formatDuration,
  keyedToasts,
  moreLabel,
  planToasts,
  QUEUED_GRACE_S,
  RESUME_MIN_MS,
  RUNNING_CAP_MS,
  summarizeChanges,
  toastKey,
  toastView,
} from "./toast.ts";

const entry = (n) => ({
  label: `Entry 'e${n}' published`,
  event: "entry_published",
  entityType: "entry",
  entityId: `id-${n}`,
});

describe("summarizeChanges", () => {
  test("lists the newest change first, entries linked", () => {
    const list = summarizeChanges(
      [entry(1), { label: "Collection 'Venues' updated", entityType: "collection", entityId: "c" }],
      2,
    );
    assert.deepEqual(list, {
      total: 2,
      items: [
        { label: "Collection 'Venues' updated", href: null },
        { label: "Entry 'e1' published", href: "/workspace/entries/id-1" },
      ],
      more: 0,
    });
  });

  test("counts requests beyond the listed changes as more", () => {
    const list = summarizeChanges([entry(1)], 5);
    assert.equal(list.total, 5);
    assert.equal(list.more, 4);
  });

  test("without a request count, the list is the total", () => {
    assert.equal(summarizeChanges([entry(1), entry(2)]).total, 2);
  });

  test("no changes means no disclosure", () => {
    assert.equal(summarizeChanges(null, 3), null);
    assert.equal(summarizeChanges([], 3), null);
  });
});

describe("labels", () => {
  test("pluralize the change count", () => {
    assert.equal(changesLabel(1), "1 change");
    assert.equal(changesLabel(3), "3 changes");
  });

  test("only entries link", () => {
    assert.equal(changeHref({ label: "x", entityType: "asset", entityId: "a" }), null);
    assert.equal(changeHref({ label: "x", entityType: "entry", entityId: null }), null);
  });

  test("say what the unlisted ones are", () => {
    assert.match(moreLabel(2), /^and 2 more/);
  });
});

describe("dismissTimer", () => {
  const withClock = (fn) => () => {
    mock.timers.enable({ apis: ["setTimeout", "Date"], now: 0 });
    try {
      fn();
    } finally {
      mock.timers.reset();
    }
  };

  test(
    "expires after its time",
    withClock(() => {
      const expired = mock.fn();
      dismissTimer(6000, expired);
      mock.timers.tick(5999);
      assert.equal(expired.mock.callCount(), 0);
      mock.timers.tick(1);
      assert.equal(expired.mock.callCount(), 1);
    }),
  );

  test(
    "pauses while held and resumes with the time that was left",
    withClock(() => {
      const expired = mock.fn();
      const timer = dismissTimer(6000, expired);
      mock.timers.tick(2000);
      timer.hold("pointer");
      mock.timers.tick(60_000);
      assert.equal(expired.mock.callCount(), 0);
      timer.release("pointer");
      mock.timers.tick(3999);
      assert.equal(expired.mock.callCount(), 0);
      mock.timers.tick(1);
      assert.equal(expired.mock.callCount(), 1);
    }),
  );

  test(
    "stays paused until every hold is released",
    withClock(() => {
      const expired = mock.fn();
      const timer = dismissTimer(6000, expired);
      timer.hold("pointer");
      timer.hold("open");
      timer.release("pointer");
      mock.timers.tick(60_000);
      assert.equal(expired.mock.callCount(), 0);
      timer.release("open");
      mock.timers.tick(6000);
      assert.equal(expired.mock.callCount(), 1);
    }),
  );

  test(
    "never resumes with less than a moment to read",
    withClock(() => {
      const expired = mock.fn();
      const timer = dismissTimer(6000, expired);
      mock.timers.tick(5900);
      timer.hold("pointer");
      timer.release("pointer");
      mock.timers.tick(RESUME_MIN_MS - 1);
      assert.equal(expired.mock.callCount(), 0);
      mock.timers.tick(1);
      assert.equal(expired.mock.callCount(), 1);
    }),
  );

  test(
    "a cancelled timer never fires",
    withClock(() => {
      const expired = mock.fn();
      dismissTimer(6000, expired).cancel();
      mock.timers.tick(10_000);
      assert.equal(expired.mock.callCount(), 0);
    }),
  );
});

// ── In-place toasts ────────────────────────────────────────────────────────────────────────────

const WS = "ws-1";
const started = (runId = "r1", extra = {}) => ({
  eventType: "automation_started",
  messageTitle: "Automation Started",
  runId,
  workflowName: "Tag all",
  ...extra,
});
const ran = (runId = "r1") => ({ eventType: "automation_ran", messageTitle: "Automation Ran", messageBody: "Automation 'tag-all' ran", runId });
const failed = (runId = "r1") => ({ eventType: "automation_failed", messageTitle: "Automation Failed", runId });
const queued = (extra = {}) => ({
  eventType: "site_rebuild_queued",
  messageTitle: "Site Rebuild Queued",
  workspaceId: WS,
  quietSeconds: 60,
  maxWaitSeconds: 600,
  ...extra,
});
const sent = (extra = {}) => ({ eventType: "webhook_triggered", messageTitle: "Webhook Triggered", workspaceId: WS, ...extra });

const OK = { tone: "ok", label: "Workflow" };
const ERR = { tone: "err", label: "Workflow failed" };
const INFO = { tone: "info", label: "Site rebuild" };

/** Each step as [eventType, action], for terse expectations. */
const actions = (steps) => steps.map((s) => [s.event.eventType, s.action]);
const nothingOpen = () => false;

describe("toastKey", () => {
  test("a rebuild is keyed by workspace, a run by its id", () => {
    assert.deepEqual(toastKey(queued()), { key: `rebuild:${WS}`, opens: true });
    assert.deepEqual(toastKey(sent()), { key: `rebuild:${WS}`, opens: false });
    assert.deepEqual(toastKey(started()), { key: "run:r1", opens: true });
    assert.deepEqual(toastKey(failed()), { key: "run:r1", opens: false });
  });

  test("an event without its id, or of another kind, has no slot", () => {
    assert.equal(toastKey(ran(null)), null);
    assert.equal(toastKey({ eventType: "entry_published", messageTitle: "x", workspaceId: WS }), null);
  });
});

describe("planToasts", () => {
  test("a start opens a pending toast that its run's end updates on a later poll", () => {
    assert.deepEqual(actions(planToasts([started()], nothingOpen)), [["automation_started", "open"]]);
    const later = planToasts([ran()], (key) => key === "run:r1");
    assert.deepEqual(later, [{ event: ran(), key: "run:r1", action: "update" }]);
  });

  test("a failed end updates the running toast too", () => {
    const steps = planToasts([failed()], (key) => key === "run:r1");
    assert.deepEqual(actions(steps), [["automation_failed", "update"]]);
  });

  test("a start and its end in the same poll show only the end", () => {
    assert.deepEqual(actions(planToasts([started(), ran()], nothingOpen)), [["automation_ran", "show"]]);
  });

  test("another run's end leaves a pending start alone", () => {
    const steps = planToasts([started("r1"), ran("r2")], nothingOpen);
    assert.deepEqual(actions(steps), [
      ["automation_started", "open"],
      ["automation_ran", "show"],
    ]);
  });

  test("an end with nothing pending is a toast of its own", () => {
    assert.deepEqual(planToasts([failed()], nothingOpen), [{ event: failed(), key: null, action: "show" }]);
  });

  test("a queued rebuild is updated by the next send in its workspace, and only that one", () => {
    const open = (key) => key === `rebuild:${WS}`;
    assert.deepEqual(actions(planToasts([sent(), sent()], open)), [
      ["webhook_triggered", "update"],
      ["webhook_triggered", "show"],
    ]);
  });

  test("a send then a new batch in one poll: the send shows, the new batch opens", () => {
    assert.deepEqual(actions(planToasts([queued(), sent(), queued()], nothingOpen)), [
      ["webhook_triggered", "show"],
      ["site_rebuild_queued", "open"],
    ]);
  });

  test("events with no slot pass straight through", () => {
    const other = { eventType: "entry_published", messageTitle: "Published" };
    assert.deepEqual(actions(planToasts([other], nothingOpen)), [["entry_published", "show"]]);
  });
});

describe("toastView", () => {
  test("a queued rebuild says when it builds, from the event's windows", () => {
    const view = toastView(queued({ quietSeconds: 45, maxWaitSeconds: 300 }), INFO);
    assert.equal(view.text, "Site rebuild queued — building in about 45 s");
    assert.equal(view.note, "More changes join this build (sent at the latest 5 min after the first)");
    assert.equal(view.lifetime, "pending");
  });

  test("a queued rebuild waits at most its max wait plus a grace", () => {
    assert.equal(toastView(queued({ maxWaitSeconds: 300 }), INFO).capMs, (300 + QUEUED_GRACE_S) * 1000);
  });

  test("the send that updates it in place says it was sent and how much it covers", () => {
    const view = toastView(sent({ requestCount: 3 }), INFO, true);
    assert.equal(view.text, "Site rebuild sent — 3 changes");
    assert.equal(view.lifetime, "auto");
  });

  test("with a change list, the list's toggle carries the count", () => {
    const changes = [{ label: "Entry 'e1' published", entityType: "entry", entityId: "e1" }];
    assert.equal(toastView(sent({ requestCount: 2, changes }), INFO, true).text, "Site rebuild sent");
  });

  test("a send that isn't updating anything keeps its own wording", () => {
    const view = toastView(sent({ messageBody: "Site rebuild requested: scheduled", requestCount: 1 }), INFO);
    assert.equal(view.text, "Site rebuild requested: scheduled");
  });

  test("a running workflow names itself and how many entries it acts on", () => {
    assert.equal(toastView(started(), OK).text, "Workflow 'Tag all' is running…");
    assert.equal(toastView(started("r1", { targetCount: 12 }), OK).text, "Workflow 'Tag all' is running… · 12 entries");
    assert.equal(toastView(started("r1", { targetCount: 1 }), OK).text, "Workflow 'Tag all' is running… · 1 entry");
    assert.equal(toastView(started(), OK).capMs, RUNNING_CAP_MS);
  });

  test("a run's end keeps its own label and tone: a success auto-dismisses, a failure stays", () => {
    assert.deepEqual([toastView(ran(), OK, true).tone, toastView(ran(), OK, true).lifetime], ["ok", "auto"]);
    const end = toastView(failed(), ERR, true);
    assert.deepEqual([end.tone, end.label, end.lifetime], ["err", "Workflow failed", "sticky"]);
  });
});

describe("formatDuration", () => {
  test("seconds, then minutes, then hours", () => {
    assert.equal(formatDuration(60), "60 s");
    assert.equal(formatDuration(120), "2 min");
    assert.equal(formatDuration(600), "10 min");
    assert.equal(formatDuration(3 * 3600), "3 h");
  });
});

describe("keyedToasts", () => {
  const withClock = (fn) => () => {
    mock.timers.enable({ apis: ["setTimeout"] });
    try {
      fn();
    } finally {
      mock.timers.reset();
    }
  };

  test(
    "a pending toast that is never ended expires at its cap",
    withClock(() => {
      const expired = mock.fn();
      const slots = keyedToasts(expired);
      slots.open(`rebuild:${WS}`, "queued-toast", 720_000);
      mock.timers.tick(719_999);
      assert.equal(expired.mock.callCount(), 0);
      mock.timers.tick(1);
      assert.deepEqual(expired.mock.calls[0].arguments, ["queued-toast"]);
      assert.equal(slots.has(`rebuild:${WS}`), false);
    }),
  );

  test(
    "taking a pending toast hands it over and cancels its cap",
    withClock(() => {
      const expired = mock.fn();
      const slots = keyedToasts(expired);
      slots.open("run:r1", "running-toast", 1000);
      assert.equal(slots.take("run:r1"), "running-toast");
      mock.timers.tick(5000);
      assert.equal(expired.mock.callCount(), 0);
      assert.equal(slots.take("run:r1"), undefined);
    }),
  );

  test(
    "reopening a slot replaces its toast and restarts the cap",
    withClock(() => {
      const expired = mock.fn();
      const slots = keyedToasts(expired);
      slots.open("run:r1", "first", 1000);
      mock.timers.tick(900);
      slots.open("run:r1", "second", 1000);
      mock.timers.tick(900);
      assert.equal(expired.mock.callCount(), 0);
      mock.timers.tick(100);
      assert.deepEqual(expired.mock.calls[0].arguments, ["second"]);
    }),
  );
});

describe("approvalTarget", () => {
  const askHref = (id) => (id ? `/ask?thread=${id}` : "/ask");
  const event = { eventType: "approval_requested", userId: "u1", entityType: "ai_thread", entityId: "root-1" };

  test("test_approval_toast_links_the_owner_to_the_ask_thread", () => {
    assert.deepEqual(approvalTarget(event, "u1", true, askHref), {
      threadId: "root-1",
      href: "/ask?thread=root-1",
      openBubble: false,
    });
  });

  test("test_approval_toast_is_only_for_the_threads_owner", () => {
    assert.equal(approvalTarget(event, "someone-else", true, askHref), null);
    assert.equal(approvalTarget(event, null, true, askHref), null);
  });

  test("test_approval_toast_opens_the_bubble_while_the_ask_page_is_off", () => {
    assert.deepEqual(approvalTarget(event, "u1", false, askHref), { threadId: "root-1", href: null, openBubble: true });
  });

  test("test_approval_toast_without_a_thread_links_the_ask_page", () => {
    assert.deepEqual(approvalTarget({ ...event, entityId: null }, "u1", true, askHref), {
      threadId: null,
      href: "/ask",
      openBubble: false,
    });
  });
});
