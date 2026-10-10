// Whose character the bubble shows (cast.ts): the per-state merge of an agent's pack over the
// workspace's, and the swaps on `/use` and during a hand-off. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { actingAgent, createCast, MAIN_AGENT, mergeStates, sameStates } from "./cast.ts";

const WORKSPACE = { idle: "/w/idle.gif", thinking: "/w/think.gif", move_left: "/w/left.gif" };
const SCOUT = { idle: "/s/idle.gif", working: "/s/run.gif" };
const AGENTS = { scout: SCOUT, plain: undefined };

describe("mergeStates", () => {
  test("an agent's own animations win, state by state, over the workspace's", () => {
    assert.deepEqual(mergeStates(SCOUT, WORKSPACE), {
      idle: "/s/idle.gif",
      thinking: "/w/think.gif",
      working: "/s/run.gif",
      move_left: "/w/left.gif", // no sideways run of its own: it drags with the workspace's
    });
  });

  test("an agent without a character shows the workspace's unchanged", () => {
    assert.equal(mergeStates(undefined, WORKSPACE), WORKSPACE);
    assert.equal(mergeStates({}, WORKSPACE), WORKSPACE);
  });

  test("an agent's character stands alone when the workspace has none", () => {
    assert.equal(mergeStates(SCOUT, null), SCOUT);
  });

  test("no character anywhere means the icon", () => {
    assert.equal(mergeStates(undefined, undefined), undefined);
  });

  test("a pack without idle isn't playable, so it adds nothing", () => {
    assert.equal(mergeStates({ working: "/x/run.gif" }, WORKSPACE), WORKSPACE);
    assert.equal(mergeStates(SCOUT, { thinking: "/w/think.gif" }), SCOUT);
  });
});

describe("actingAgent", () => {
  test("the newest event's delegate is acting", () => {
    assert.equal(actingAgent([{}, { via: "scout" }], MAIN_AGENT), "scout");
  });

  test("once the run's own agent emits again, the hand-off is over", () => {
    assert.equal(actingAgent([{ via: "scout" }, {}], MAIN_AGENT), MAIN_AGENT);
  });

  test("no events yet: the active agent", () => {
    assert.equal(actingAgent([], "scout"), "scout");
  });
});

describe("createCast", () => {
  test("starts on the active agent's character", () => {
    assert.ok(sameStates(createCast(WORKSPACE, AGENTS).states, WORKSPACE));
    assert.equal(createCast(WORKSPACE, AGENTS, "scout").states?.working, "/s/run.gif");
  });

  test("/use swaps to the agent's character and /use marvin swaps back", () => {
    const cast = createCast(WORKSPACE, AGENTS);
    assert.equal(cast.use("scout"), true);
    assert.equal(cast.states?.idle, "/s/idle.gif");
    assert.equal(cast.use(MAIN_AGENT), true);
    assert.ok(sameStates(cast.states, WORKSPACE));
  });

  test("/use of an agent without a character changes nothing", () => {
    const cast = createCast(WORKSPACE, AGENTS);
    assert.equal(cast.use("plain"), false);
    assert.equal(cast.use("unknown"), false);
    assert.ok(sameStates(cast.states, WORKSPACE));
  });

  test("a hand-off shows the delegate while it works, then the main character when the answer lands", () => {
    const cast = createCast(WORKSPACE, AGENTS);
    assert.equal(cast.progress([{ type: "thinking" }]), false);
    assert.equal(cast.progress([{ type: "thinking" }, { type: "tool_call", via: "scout" }]), true);
    assert.equal(cast.acting, "scout");
    assert.equal(cast.states?.working, "/s/run.gif");
    // Later polls of the same delegate keep it without a swap.
    assert.equal(
      cast.progress([
        { type: "tool_call", via: "scout" },
        { type: "tool_result", via: "scout" },
      ]),
      false,
    );
    assert.equal(cast.use(MAIN_AGENT), true); // the answer landed: the active agent again
    assert.equal(cast.acting, MAIN_AGENT);
    assert.ok(sameStates(cast.states, WORKSPACE));
  });

  test("a hand-off's answer stays with the delegate until the next message", () => {
    const cast = createCast(WORKSPACE, AGENTS);
    cast.progress([{ type: "tool_call" }, { type: "thinking", via: "scout" }]);
    cast.progress([{ type: "tool_call" }, { type: "thinking", via: "scout" }, { type: "answer" }]); // the router writes the reply
    assert.equal(cast.acting, MAIN_AGENT);
    assert.equal(cast.settle("reply", MAIN_AGENT), true); // the answer landed: it was scout's
    assert.equal(cast.acting, "scout");
    assert.equal(cast.states?.working, "/s/run.gif");
    assert.equal(cast.use(MAIN_AGENT), true); // the next message hands back
    assert.ok(sameStates(cast.states, WORKSPACE));
  });

  test("a run without a hand-off, or one that failed, settles on the active agent", () => {
    const cast = createCast(WORKSPACE, AGENTS);
    cast.progress([{ type: "thinking" }]);
    assert.equal(cast.settle("reply", MAIN_AGENT), false);
    cast.progress([{ via: "scout" }]);
    assert.equal(cast.settle("error", MAIN_AGENT), true); // the delegate showed while working; an error hands back
    assert.equal(cast.acting, MAIN_AGENT);
    cast.progress([{ via: "scout" }]);
    cast.use(MAIN_AGENT); // a new message forgets the last run's delegate
    assert.equal(cast.settle("reply", MAIN_AGENT), false);
    assert.equal(cast.acting, MAIN_AGENT);
  });

  test("a hand-off under /use is followed from, and handed back to, the used agent", () => {
    const cast = createCast(WORKSPACE, { ...AGENTS, helper: { idle: "/h/idle.gif" } }, "scout");
    cast.progress([{ via: "helper" }]);
    assert.equal(cast.states?.idle, "/h/idle.gif");
    cast.progress([{ via: "helper" }, {}]); // the run's own agent (scout) emits again
    assert.equal(cast.acting, "scout");
    assert.equal(cast.states?.idle, "/s/idle.gif");
  });

  test("an agent's character shows even when the workspace has only its icon", () => {
    const cast = createCast(undefined, AGENTS);
    assert.equal(cast.states, undefined);
    assert.equal(cast.hasAny, true);
    assert.equal(cast.use("scout"), true);
    assert.equal(cast.states, SCOUT);
    assert.equal(cast.use("scout"), false); // a run under it ends: nothing to swap
    assert.equal(cast.use(MAIN_AGENT), true);
    assert.equal(cast.states, undefined); // back to the icon
  });

  test("the main agent never plays an agent pack, even one stored under its slug", () => {
    const cast = createCast(WORKSPACE, { [MAIN_AGENT]: SCOUT });
    assert.ok(sameStates(cast.states, WORKSPACE));
  });

  test("hasAny is false with no character anywhere", () => {
    assert.equal(createCast(null, { plain: undefined }).hasAny, false);
  });
});
