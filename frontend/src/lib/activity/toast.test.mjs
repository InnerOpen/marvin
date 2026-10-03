// Activity toaster helpers (toast.ts). Run with `npm test` — plain `node --test`, which strips
// toast.ts's types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, mock, test } from "node:test";

import { changeHref, changesLabel, dismissTimer, moreLabel, RESUME_MIN_MS, summarizeChanges } from "./toast.ts";

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
