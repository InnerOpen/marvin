// The bubble character's state machine (character.ts). Run with `npm test` — plain `node --test`,
// which strips character.ts's types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  createCharacter,
  dragDirection,
  ERROR_HOLD_MS,
  GREETING_MS,
  IDLE_VARIANT_MAX_MS,
  IDLE_VARIANT_MIN_MS,
  imageFor,
  SUCCESS_MS,
} from "./character.ts";

const FULL = {
  idle: "/a/idle.gif",
  idle_variant: "/a/look.gif",
  greeting: "/a/wave.gif",
  thinking: "/a/review.gif",
  working: "/a/run.gif",
  waiting: "/a/wait.gif",
  success: "/a/jump.gif",
  error: "/a/failed.gif",
  move_left: "/a/left.gif",
  move_right: "/a/right.gif",
};

/** A character on a fake clock: `advance(ms)` fires whatever timer falls due. */
function rig(states = FULL, { reducedMotion = false, random = 0 } = {}) {
  const views = [];
  let now = 0;
  let timers = [];
  let nextId = 1;
  const character = createCharacter(states, {
    render: (v) => views.push(v),
    reducedMotion,
    setTimer: (fn, ms) => {
      const id = nextId++;
      timers.push({ id, at: now + ms, fn });
      return id;
    },
    clearTimer: (id) => {
      timers = timers.filter((t) => t.id !== id);
    },
    random: () => random,
  });
  function advance(ms) {
    const until = now + ms;
    for (;;) {
      const due = timers.filter((t) => t.at <= until).sort((a, b) => a.at - b.at)[0];
      if (!due) break;
      timers = timers.filter((t) => t !== due);
      now = due.at;
      due.fn();
    }
    now = until;
  }
  return { character, views, advance, pending: () => timers.length };
}

describe("imageFor", () => {
  test("test_image_for_uses_the_states_own_image", () => {
    assert.equal(imageFor(FULL, "greeting"), "/a/wave.gif");
  });

  test("test_image_for_falls_back_to_idle", () => {
    assert.equal(imageFor({ idle: "/i.gif" }, "success"), "/i.gif");
  });

  test("test_image_for_drag_falls_back_to_working_then_idle", () => {
    assert.equal(imageFor({ idle: "/i.gif", working: "/w.gif" }, "move_left"), "/w.gif");
    assert.equal(imageFor({ idle: "/i.gif" }, "move_right"), "/i.gif");
  });
});

describe("dragDirection", () => {
  test("test_drag_direction_follows_the_sign_of_dx", () => {
    assert.equal(dragDirection(-5), "drag_left");
    assert.equal(dragDirection(5), "drag_right");
  });

  test("test_drag_direction_ignores_jitter", () => {
    assert.equal(dragDirection(1), null);
    assert.equal(dragDirection(-1), null);
  });
});

describe("createCharacter", () => {
  test("test_character_starts_idle", () => {
    const { character, views } = rig();
    assert.equal(character.state, "idle");
    assert.deepEqual(views, [{ state: "idle", src: "/a/idle.gif" }]);
  });

  test("test_one_shot_greeting_returns_to_idle", () => {
    const { character, advance } = rig();
    character.dispatch("open");
    assert.equal(character.state, "greeting");
    advance(GREETING_MS);
    assert.equal(character.state, "idle");
  });

  test("test_reply_plays_success_once_then_idles", () => {
    const { character, advance } = rig();
    character.dispatch("send");
    character.dispatch("reply");
    advance(SUCCESS_MS - 1);
    assert.equal(character.state, "success");
    advance(1);
    assert.equal(character.state, "idle");
  });

  test("test_error_holds_then_idles", () => {
    const { character, advance } = rig();
    character.dispatch("error");
    advance(ERROR_HOLD_MS - 1);
    assert.equal(character.state, "error");
    advance(1);
    assert.equal(character.state, "idle");
  });

  test("test_a_run_goes_thinking_working_waiting_and_holds", () => {
    const { character, advance } = rig();
    character.dispatch("send");
    assert.equal(character.state, "thinking");
    character.dispatch("progress");
    assert.equal(character.state, "working");
    character.dispatch("parked");
    advance(IDLE_VARIANT_MAX_MS * 2);
    assert.equal(character.state, "waiting");
  });

  test("test_newer_event_wins_over_a_pending_one_shot", () => {
    const { character, advance } = rig();
    character.dispatch("open");
    character.dispatch("send");
    advance(GREETING_MS * 2); // the greeting's return-to-idle must not fire over "thinking"
    assert.equal(character.state, "thinking");
  });

  test("test_repeated_progress_does_not_rerender", () => {
    const { character, views } = rig();
    character.dispatch("progress");
    character.dispatch("progress");
    assert.equal(views.filter((v) => v.state === "working").length, 1);
  });

  test("test_drag_faces_the_way_it_moves_and_drop_idles", () => {
    const { character } = rig();
    character.dispatch("drag_left");
    assert.equal(character.state, "move_left");
    character.dispatch("drag_right");
    assert.equal(character.state, "move_right");
    character.dispatch("drop");
    assert.equal(character.state, "idle");
  });

  test("test_progress_does_not_interrupt_a_drag", () => {
    const { character } = rig();
    character.dispatch("drag_left");
    character.dispatch("progress");
    assert.equal(character.state, "move_left");
  });

  test("test_idle_fidgets_within_the_window_then_returns", () => {
    const { character, advance } = rig(FULL, { random: 0.5 });
    const due = IDLE_VARIANT_MIN_MS + 0.5 * (IDLE_VARIANT_MAX_MS - IDLE_VARIANT_MIN_MS);
    advance(due - 1);
    assert.equal(character.state, "idle");
    advance(1);
    assert.equal(character.state, "idle_variant");
    advance(IDLE_VARIANT_MAX_MS);
    assert.notEqual(character.state, "idle_variant");
  });

  test("test_no_fidget_without_an_idle_variant", () => {
    const { pending } = rig({ idle: "/i.gif" });
    assert.equal(pending(), 0);
  });

  test("test_missing_states_render_the_fallback_image", () => {
    const { character, views } = rig({ idle: "/i.gif" });
    character.dispatch("open");
    assert.deepEqual(views.at(-1), { state: "greeting", src: "/i.gif" });
  });

  test("test_stop_cancels_pending_timers", () => {
    const { character, pending } = rig();
    character.dispatch("open");
    character.stop();
    assert.equal(pending(), 0);
  });
});

describe("reduced motion", () => {
  test("test_reduced_motion_never_fidgets", () => {
    const { character, advance, pending } = rig(FULL, { reducedMotion: true });
    assert.equal(pending(), 0);
    advance(IDLE_VARIANT_MAX_MS * 2);
    assert.equal(character.state, "idle");
  });

  test("test_reduced_motion_ignores_dragging", () => {
    const { character, views } = rig(FULL, { reducedMotion: true });
    character.dispatch("drag_left");
    character.dispatch("drop");
    assert.equal(character.state, "idle");
    assert.equal(views.length, 1);
  });

  test("test_reduced_motion_still_swaps_stills_on_state_changes", () => {
    const { character, views } = rig(FULL, { reducedMotion: true });
    character.dispatch("send");
    assert.deepEqual(views.at(-1), { state: "thinking", src: "/a/review.gif" });
  });
});
