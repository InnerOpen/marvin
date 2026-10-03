// Pending-run recovery (pending.ts). Run with `npm test` — plain `node --test`, which strips
// pending.ts's types itself; no test framework to install. Plain JS so `astro check` (which has no
// Node typings here) leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  assess,
  askThreadHref,
  findReply,
  forgetConversation,
  learnWhileInFlight,
  loadPending,
  newRunId,
  ownsPending,
  PENDING_RUN_TIMEOUT_MS,
  PROGRESS_MISSING_GRACE_MS,
  recoverPendingRun,
  rememberThread,
  savePending,
  threadFor,
  withProgress,
} from "./pending.ts";

const T0 = 1_000_000;

function memoryStore() {
  const data = new Map();
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
  };
}

const run = (over = {}) => ({ clientRunId: "run-1", agent: "marvin", message: "what changed?", sentAt: T0, ...over });
const progress = (status, over = {}) => ({ id: "run-1", status, events: [], ...over });
const msg = (seq, role, content, executionId = null) => ({ id: `m${seq}`, seq, role, content, executionId });
const thread = (messages, over = {}) => ({ id: "th-1", status: "open", messages, pending: [], ...over });
const observe = (over = {}) => ({ now: T0 + 1000, progress: null, thread: null, missingSince: null, ...over });

describe("withProgress", () => {
  test("test_with_progress_learns_thread_and_execution_ids", () => {
    const next = withProgress(run(), progress("running", { threadId: "th-1", executionId: "ex-1" }));
    assert.equal(next.threadId, "th-1");
    assert.equal(next.executionId, "ex-1");
  });

  test("test_with_progress_returns_the_same_run_when_nothing_is_new", () => {
    const r = run({ threadId: "th-1" });
    assert.equal(withProgress(r, progress("running", { threadId: "th-1" })), r);
    assert.equal(withProgress(r, null), r);
  });
});

describe("findReply", () => {
  test("test_find_reply_matches_the_runs_execution", () => {
    const t = thread([
      msg(1, "user", "what changed?"),
      msg(2, "assistant", "old", "ex-0"),
      msg(3, "user", "what changed?"),
      msg(4, "assistant", "new", "ex-1"),
    ]);
    assert.equal(findReply(t, run({ executionId: "ex-1" })).content, "new");
    assert.equal(findReply(t, run({ executionId: "ex-9" })), null);
  });

  test("test_find_reply_without_an_execution_id_takes_the_turn_after_the_latest_matching_question", () => {
    const t = thread([
      msg(1, "user", "what changed?"),
      msg(2, "assistant", "old"),
      msg(3, "user", "what changed?"),
      msg(4, "assistant", "new"),
    ]);
    assert.equal(findReply(t, run()).content, "new");
  });

  test("test_find_reply_is_null_while_the_answer_is_not_stored_yet", () => {
    assert.equal(findReply(thread([msg(1, "user", "earlier"), msg(2, "assistant", "ok")]), run()), null);
  });
});

describe("assess", () => {
  test("test_assess_waits_while_the_run_is_running", () => {
    assert.deepEqual(assess(run(), observe({ progress: progress("running") })), { kind: "wait" });
  });

  test("test_assess_reports_a_failed_run_with_the_servers_reason", () => {
    const verdict = assess(
      run({ threadId: "th-1" }),
      observe({ progress: progress("failed", { error: "Agent failed: down" }) }),
    );
    assert.deepEqual(verdict, { kind: "failed", error: "Agent failed: down", threadId: "th-1" });
  });

  test("test_assess_returns_the_reply_once_it_is_in_the_thread", () => {
    const t = thread([msg(1, "user", "what changed?"), msg(2, "assistant", "lots", "ex-1")]);
    const verdict = assess(run({ executionId: "ex-1" }), observe({ progress: progress("completed"), thread: t }));
    assert.equal(verdict.kind, "reply");
    assert.equal(verdict.message.content, "lots");
  });

  test("test_assess_reports_a_parked_run_with_its_tools", () => {
    const p = progress("awaiting_approval", {
      threadId: "th-1",
      events: [{ type: "awaiting_approval", calls: [{ id: "c1", tool: "attach_tag" }], at: 1 }],
    });
    assert.deepEqual(assess(run(), observe({ progress: p })), {
      kind: "parked",
      threadId: "th-1",
      tools: ["attach_tag"],
    });
  });

  test("test_assess_sees_a_park_in_the_thread_when_progress_is_gone", () => {
    const t = thread([msg(1, "user", "what changed?")], {
      status: "awaiting_approval",
      pending: [{ id: "c1", tool: "compose_entry" }],
    });
    assert.deepEqual(assess(run({ threadId: "th-1" }), observe({ thread: t, missingSince: T0 })), {
      kind: "parked",
      threadId: "th-1",
      tools: ["compose_entry"],
    });
  });

  test("test_assess_waits_through_a_short_unknown_spell_then_calls_the_run_lost", () => {
    const early = observe({ now: T0 + PROGRESS_MISSING_GRACE_MS, missingSince: T0 });
    assert.deepEqual(assess(run(), early), { kind: "wait" });
    const late = observe({ now: T0 + PROGRESS_MISSING_GRACE_MS + 1, missingSince: T0 });
    assert.deepEqual(assess(run(), late), { kind: "lost", timedOut: false, threadId: undefined });
  });

  test("test_assess_gives_up_after_the_timeout_even_while_running", () => {
    const verdict = assess(
      run({ threadId: "th-1" }),
      observe({ now: T0 + PENDING_RUN_TIMEOUT_MS + 1, progress: progress("running") }),
    );
    assert.deepEqual(verdict, { kind: "lost", timedOut: true, threadId: "th-1" });
  });
});

describe("recoverPendingRun", () => {
  function deps(polls, threads = {}) {
    const calls = { thread: [], updates: [] };
    let now = T0;
    return {
      calls,
      getRunProgress: async () => {
        const next = polls.shift();
        if (!next) throw new Error("404");
        return next;
      },
      getThread: async (id) => {
        calls.thread.push(id);
        return threads[id];
      },
      sleep: async (ms) => {
        now += ms;
      },
      now: () => now,
      onUpdate: (r) => calls.updates.push(r),
    };
  }

  test("test_recover_follows_progress_to_the_stored_reply_and_saves_the_learned_ids", async () => {
    const d = deps(
      [
        progress("running", { threadId: "th-1", executionId: "ex-1" }),
        progress("completed", { threadId: "th-1", executionId: "ex-1" }),
      ],
      { "th-1": thread([msg(1, "user", "what changed?"), msg(2, "assistant", "lots", "ex-1")]) },
    );
    const verdict = await recoverPendingRun(run(), d);
    assert.equal(verdict.kind, "reply");
    assert.equal(verdict.message.content, "lots");
    assert.deepEqual(d.calls.thread, ["th-1"]); // not fetched while the run was still running
    assert.equal(d.calls.updates.length, 1);
    assert.equal(d.calls.updates[0].executionId, "ex-1");
  });

  test("test_recover_finds_the_answer_in_a_known_thread_after_progress_expired", async () => {
    const d = deps([], { "th-1": thread([msg(1, "user", "what changed?"), msg(2, "assistant", "lots")]) });
    const verdict = await recoverPendingRun(run({ threadId: "th-1" }), d);
    assert.equal(verdict.kind, "reply");
  });

  test("test_recover_stops_when_cancelled", async () => {
    const d = { ...deps([progress("running")]), isCancelled: () => true };
    assert.deepEqual(await recoverPendingRun(run(), d), { kind: "cancelled" });
  });
});

describe("learnWhileInFlight", () => {
  test("test_learn_while_in_flight_reports_ids_and_stops_once_known", async () => {
    const updates = [];
    let polls = 0;
    const settled = new Promise((resolve) => {
      learnWhileInFlight(run(), {
        sleep: async () => {},
        getRunProgress: async () => {
          polls += 1;
          return polls === 1 ? progress("running") : progress("running", { threadId: "th-1", executionId: "ex-1" });
        },
        onUpdate: (r) => {
          updates.push(r);
          resolve();
        },
      });
    });
    await settled;
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(updates.length, 1);
    assert.equal(updates[0].threadId, "th-1");
    assert.equal(polls, 2);
  });

  test("test_learn_while_in_flight_reports_nothing_after_stop", async () => {
    const updates = [];
    const stop = learnWhileInFlight(run(), {
      sleep: () => new Promise((resolve) => setTimeout(resolve, 5)),
      getRunProgress: async () => progress("running", { threadId: "th-1", executionId: "ex-1" }),
      onUpdate: (r) => updates.push(r),
    });
    stop();
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.equal(updates.length, 0);
  });

  test("test_learn_while_in_flight_keeps_reporting_progress_while_someone_listens", async () => {
    const seen = [];
    const third = new Promise((resolve) => {
      const stop = learnWhileInFlight(run(), {
        sleep: async () => {},
        getRunProgress: async () => progress("running", { threadId: "th-1", executionId: "ex-1" }),
        onProgress: (p) => {
          seen.push(p);
          if (seen.length === 3) {
            stop();
            resolve();
          }
        },
      });
    });
    await third;
    assert.equal(seen.length, 3); // past the first answer that already named both ids
  });
});

describe("storage", () => {
  test("test_threads_are_remembered_per_agent", () => {
    const store = memoryStore();
    rememberThread("marvin", "th-1", store);
    rememberThread("workshop", "th-2", store);
    assert.equal(threadFor("marvin", store), "th-1");
    assert.equal(threadFor("workshop", store), "th-2");
    rememberThread("marvin", null, store);
    assert.equal(threadFor("marvin", store), undefined);
  });

  test("test_forget_conversation_drops_threads_and_the_pending_run", () => {
    const store = memoryStore();
    rememberThread("marvin", "th-1", store);
    savePending(run(), store);
    assert.equal(ownsPending(run(), store), true);
    forgetConversation(store);
    assert.equal(threadFor("marvin", store), undefined);
    assert.equal(loadPending(store), null);
    assert.equal(ownsPending(run(), store), false);
  });

  test("test_corrupt_storage_reads_as_empty", () => {
    const store = memoryStore();
    store.setItem("marvin.pending", "{not json");
    assert.equal(loadPending(store), null);
  });
});

test("test_new_run_id_is_a_v4_uuid", () => {
  assert.match(newRunId(), /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});

test("test_ask_thread_href_opens_the_thread_when_known", () => {
  assert.equal(askThreadHref("th 1"), "/workspace/settings/ai-ask?thread=th%201");
  assert.equal(askThreadHref(), "/workspace/settings/ai-ask");
});
