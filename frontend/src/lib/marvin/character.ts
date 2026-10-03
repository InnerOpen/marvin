/**
 * Marvin — the bubble's animated character: which animation plays when.
 *
 * A character is a map of canonical bubble states to image URLs (AI settings → Persona → Bubble
 * character; the backend's services/ai/character.py owns the state list and the filename aliases, and
 * these keys must match it). Only that resolved map drives this — where the images live is not its
 * concern. The bubble feeds in what happens (panel opened, message sent, agent working, reply…) and
 * renders whatever image this hands back.
 *
 * Kept free of the DOM, with timers and randomness passed in, so it runs under `node --test`
 * (character.test.mjs).
 */

export const CHARACTER_STATES = [
  "idle",
  "idle_variant",
  "greeting",
  "thinking",
  "working",
  "waiting",
  "success",
  "error",
  "move_left",
  "move_right",
] as const;
export type CharacterState = (typeof CHARACTER_STATES)[number];
export type CharacterStates = Partial<Record<CharacterState, string>>;

/** Where a state looks when the pack has no animation for it; every chain ends at idle. */
const FALLBACKS: Record<CharacterState, CharacterState[]> = {
  idle: [],
  idle_variant: ["idle"],
  greeting: ["idle"],
  thinking: ["idle"],
  working: ["idle"],
  waiting: ["idle"],
  success: ["idle"],
  error: ["idle"],
  // Being dragged is running about, so a pack without a sideways run uses its plain one.
  move_left: ["working", "idle"],
  move_right: ["working", "idle"],
};

/** What happened, as the bubble reports it. */
export type CharacterEvent =
  | "open" // the panel opened
  | "send" // a message went out
  | "progress" // the agent took a step
  | "parked" // the run waits on the user's approval
  | "reply" // the answer arrived
  | "error" // the run failed
  | "rest" // nothing more to show (a run was abandoned)
  | "drag_left"
  | "drag_right"
  | "drop";

const EVENT_STATE: Record<CharacterEvent, CharacterState> = {
  open: "greeting",
  send: "thinking",
  progress: "working",
  parked: "waiting",
  reply: "success",
  error: "error",
  rest: "idle",
  drag_left: "move_left",
  drag_right: "move_right",
  drop: "idle",
};

// A GIF's length can't be read from an <img>, so one-shot states play for a fixed time: about two
// loops of a typical one-second animation — long enough to read, short enough not to linger.
export const GREETING_MS = 2_000;
export const SUCCESS_MS = 2_000;
export const IDLE_VARIANT_MS = 2_600;
/** An error stays up a little longer: it's news the user should catch. */
export const ERROR_HOLD_MS = 4_000;

/** States that play once and hand back to idle, and for how long. */
const ONE_SHOT_MS: Partial<Record<CharacterState, number>> = {
  greeting: GREETING_MS,
  success: SUCCESS_MS,
  idle_variant: IDLE_VARIANT_MS,
  error: ERROR_HOLD_MS,
};

/** While idle, the fidget plays once at a random moment in this window — a fixed beat looks mechanical. */
export const IDLE_VARIANT_MIN_MS = 20_000;
export const IDLE_VARIANT_MAX_MS = 40_000;

/** Pointer movement below this many pixels doesn't turn the character round (jitter). */
export const DRAG_DIRECTION_MIN_PX = 2;

const DRAG_EVENTS: ReadonlySet<CharacterEvent> = new Set(["drag_left", "drag_right", "drop"]);
const DRAG_STATES: ReadonlySet<CharacterState> = new Set(["move_left", "move_right"]);

/** The states `state` borrows from, in order, when the pack has no animation of its own for it. */
export function fallbacksOf(state: CharacterState): readonly CharacterState[] {
  return FALLBACKS[state];
}

/** The image for `state`, following the fallback chain; undefined only when the pack lacks idle too. */
export function imageFor(states: CharacterStates, state: CharacterState): string | undefined {
  for (const s of [state, ...FALLBACKS[state]]) {
    if (states[s]) return states[s];
  }
  return undefined;
}

/** Which way a drag step of `dx` pixels faces the character, or null for jitter. */
export function dragDirection(dx: number): "drag_left" | "drag_right" | null {
  if (Math.abs(dx) < DRAG_DIRECTION_MIN_PX) return null;
  return dx < 0 ? "drag_left" : "drag_right";
}

export interface CharacterView {
  state: CharacterState;
  src: string;
}

export interface CharacterDeps {
  /** Show this image; called on every change of state. */
  render(view: CharacterView): void;
  /**
   * prefers-reduced-motion: the bubble shows stills, and nothing here adds motion of its own — no
   * idle fidget, no running about while dragged. Other state changes still swap the still.
   */
  reducedMotion: boolean;
  setTimer(fn: () => void, ms: number): unknown;
  clearTimer(id: unknown): void;
  /** In [0, 1), like Math.random. */
  random(): number;
}

export interface Character {
  dispatch(event: CharacterEvent): void;
  readonly state: CharacterState;
  /** Cancel pending timers (the character is being replaced). */
  stop(): void;
}

/** A character showing idle, driven by dispatch(); the newest event always wins. */
export function createCharacter(states: CharacterStates, deps: CharacterDeps): Character {
  let current: CharacterState = "idle";
  let timer: unknown;

  function clear() {
    if (timer !== undefined) deps.clearTimer(timer);
    timer = undefined;
  }

  function enter(state: CharacterState) {
    clear();
    current = state;
    deps.render({ state, src: imageFor(states, state) ?? "" });
    const hold = ONE_SHOT_MS[state];
    if (hold !== undefined) timer = deps.setTimer(() => enter("idle"), hold);
    else if (state === "idle") scheduleFidget();
  }

  function scheduleFidget() {
    if (deps.reducedMotion || !states.idle_variant) return;
    const wait = IDLE_VARIANT_MIN_MS + deps.random() * (IDLE_VARIANT_MAX_MS - IDLE_VARIANT_MIN_MS);
    timer = deps.setTimer(() => enter("idle_variant"), wait);
  }

  enter("idle");

  return {
    dispatch(event) {
      if (deps.reducedMotion && DRAG_EVENTS.has(event)) return;
      const next = EVENT_STATE[event];
      // Progress polls keep coming while a run lasts: they mustn't yank the character out of a drag.
      if (event === "progress" && DRAG_STATES.has(current)) return;
      // A held state asked for again carries on as it is; a one-shot asked for again starts over.
      if (next === current && ONE_SHOT_MS[next] === undefined) return;
      enter(next);
    },
    get state() {
      return current;
    },
    stop: clear,
  };
}
