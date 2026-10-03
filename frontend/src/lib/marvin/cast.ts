/**
 * Marvin — whose character the bubble shows: the workspace's, or an agent's.
 *
 * Agents can have a bubble character of their own (Settings → Agents). The bubble shows the character
 * of whichever agent is talking: the active one (`/use <agent>`, until `/use marvin`), or — while a
 * router hand-off works — the delegate, which the run's live progress events name in `via`. When the
 * answer lands it goes back to the active agent's.
 *
 * An agent's pack covers what it covers, state by state: a state it has no animation for plays the
 * workspace's (an agent pack without a sideways run still drags with the workspace's), and with no
 * character anywhere the bubble shows its icon. The main agent (`marvin`) *is* the workspace's character.
 *
 * Pure — no DOM, no fetching — so it runs under `node --test` (cast.test.mjs). character.ts stays the
 * state machine that plays whichever states this picks.
 */

import type { CharacterStates } from "./character";

/** The main agent: its character is the workspace's. */
export const MAIN_AGENT = "marvin";

/** {agent slug: states} for the agents that have a character of their own. */
export type AgentCharacters = Readonly<Record<string, CharacterStates | undefined>>;

/** A run's live event, as far as this cares: who emitted it (a delegate's slug; unset for the run's own agent). */
export interface ActingEvent {
  via?: string;
}

/** A usable character: one with an idle animation (every other state falls back to it). */
function playable(states: CharacterStates | null | undefined): CharacterStates | undefined {
  return states?.idle ? states : undefined;
}

/**
 * The states to play for an agent: its own where it has them, the workspace's for the rest; undefined
 * when neither has a character (the bubble shows its icon).
 */
export function mergeStates(
  agent: CharacterStates | null | undefined,
  workspace: CharacterStates | null | undefined,
): CharacterStates | undefined {
  const own = playable(agent);
  const base = playable(workspace);
  if (!own) return base;
  if (!base) return own;
  const merged: CharacterStates = { ...base };
  for (const [state, src] of Object.entries(own) as [keyof CharacterStates, string | undefined][]) {
    if (src) merged[state] = src;
  }
  return merged;
}

/** Who is acting in a run: the delegate the newest event came from, else the run's own (active) agent. */
export function actingAgent(events: readonly ActingEvent[], active: string): string {
  return events.at(-1)?.via || active;
}

/** Whether two characters show the same images for every state. */
export function sameStates(a: CharacterStates | undefined, b: CharacterStates | undefined): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  const keys = new Set([...Object.keys(a), ...Object.keys(b)] as (keyof CharacterStates)[]);
  return [...keys].every((k) => a[k] === b[k]);
}

export interface Cast {
  /** The states to show now; undefined → the icon. */
  readonly states: CharacterStates | undefined;
  /** The agent whose character is showing (or would be, if it had one). */
  readonly acting: string;
  /** Whether anyone — the workspace or an agent — has a character to show. */
  readonly hasAny: boolean;
  /**
   * The agent talking now is the active one: after `/use`, and when a run ends (answer, error,
   * abandoned) — a hand-off's delegate gives the bubble back.
   */
  use(slug: string): boolean;
  /** A progress poll of the running run: a delegate may have taken over, or handed back. */
  progress(events: readonly ActingEvent[]): boolean;
}

/**
 * Tracks who's talking and what to show. Every method returns whether `states` changed — the bubble
 * swaps the character only then, so the animation isn't restarted for nothing.
 */
export function createCast(workspace: CharacterStates | null | undefined, agents: AgentCharacters, active: string = MAIN_AGENT): Cast {
  let activeSlug = active || MAIN_AGENT;
  let acting = activeSlug;
  const statesFor = (slug: string) => mergeStates(slug === MAIN_AGENT ? undefined : agents[slug], workspace);
  let states = statesFor(acting);

  function actAs(slug: string): boolean {
    acting = slug;
    const next = statesFor(slug);
    const changed = !sameStates(states, next);
    states = next;
    return changed;
  }

  return {
    get states() {
      return states;
    },
    get acting() {
      return acting;
    },
    get hasAny() {
      return !!playable(workspace) || Object.values(agents).some((s) => !!playable(s));
    },
    use(slug) {
      activeSlug = slug || MAIN_AGENT;
      return actAs(activeSlug);
    },
    progress(events) {
      return actAs(actingAgent(events, activeSlug));
    },
  };
}
