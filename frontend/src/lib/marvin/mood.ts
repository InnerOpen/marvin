// The Social Battery in the bubble: how the character feels about this person (services/ai/mood.py), as the run reports it
// and as GET /api/ai/mood answers when the panel opens. Pure: what the band changes (greetings and taglines from the band's
// own lines, the idle state), the little battery in the header, and what /mood says. Marvin.astro draws it.

import type { CharacterState, CharacterStates } from "./character";
import type { Voice } from "./persona";

export type MoodBand = "low" | "neutral" | "high";

/** The meter as the API reports it: the number is null while the character hides its meter. */
export interface MoodState {
  level: number | null;
  band: MoodBand | string;
  visible: boolean;
}

export interface MoodBandLines {
  greetings?: string[];
  taglines?: string[];
}

/** A character's mood settings (the parts the bubble reads). */
export interface MoodLines {
  meter?: "visible" | "hidden" | null;
  low?: MoodBandLines | null;
  high?: MoodBandLines | null;
}

const esc = (s: unknown) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);

const clean = (lines: unknown): string[] =>
  Array.isArray(lines) ? lines.filter((l): l is string => typeof l === "string" && l.trim().length > 0) : [];

/** The voice in this mood: the band's greetings and taglines where the character has them, its usual ones otherwise. */
export function moodVoice(voice: Voice, mood: MoodLines | null | undefined, band: string | null | undefined): Voice {
  if (!mood || (band !== "low" && band !== "high")) return voice;
  const lines = mood[band];
  const greetings = clean(lines?.greetings);
  const taglines = clean(lines?.taglines);
  return { ...voice, greetings: greetings.length ? greetings : voice.greetings, taglines: taglines.length ? taglines : voice.taglines };
}

/** The state a low mood rests in, when the pack can show it (a slumped wait reads as drained); idle otherwise. */
export function restState(band: string | null | undefined, states: CharacterStates | null | undefined): CharacterState {
  return band === "low" && states?.waiting ? "waiting" : "idle";
}

const GLYPHS: Record<string, string> = { low: "🪫", neutral: "🔋", high: "🔋" };

/** The little battery beside the name: hidden while the character keeps its meter to itself, or the feature is off. */
export function batteryHtml(state: MoodState | null | undefined, name: string): string {
  if (!state || !state.visible || state.level == null) return "";
  const glyph = GLYPHS[state.band] ?? GLYPHS.neutral;
  return `<span class="marvin-battery mood-${esc(state.band)}" title="${esc(moodText(state, name))}" aria-label="Social Battery ${state.level} of 100"><span aria-hidden="true">${glyph}</span><span class="marvin-battery-level">${state.level}</span></span>`;
}

/** What /mood says (and the battery's tooltip): the level, what it means, and that it's a game. */
export function moodText(state: MoodState | null | undefined, name: string): string {
  if (!state) return `${name} isn't keeping a Social Battery in this workspace. An admin can switch it on under AI settings → Persona.`;
  const feel = state.band === "low" ? "running low" : state.band === "high" ? "doing well" : "about even";
  const number = state.level == null ? `${name} keeps the number to itself` : `${state.level} of 100`;
  return `Social Battery: ${number} — ${feel}. It's a game: how ${name} feels about you changes its greetings and asides, never the help. Thanks and patience charge it; rudeness aimed at ${name} drains it. Reset it any time with /mood reset.`;
}
