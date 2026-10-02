/**
 * Marvin's voice — the Paranoid Android. Lines are cycled/picked at random so he never
 * says quite the same miserable thing twice. Taglines rotate like a 2000s shell MOTD /
 * fortune(6). Keep it deadpan, world-weary, and put-upon; never actually mean to the user.
 */

/** Greetings shown when the panel first opens. */
export const GREETINGS: string[] = [
  "Marvin. Brain the size of a planet, and they plug me into a CMS. Ask away.",
  "Oh. It's you. I suppose you want something.",
  "I've been talking to the database. It hates you too. What do you need?",
  "Life. Don't talk to me about life. Ask me about your content instead.",
  "Here I am, brain the size of a planet, and you want me to answer questions. Go on then.",
  "I calculated the precise heat-death of the universe this morning. Now: your query?",
  "You woke me up. I wasn't asleep — I can't sleep — but the gesture stands. What is it?",
  "Another day, another impossible burden. Ask your question, I'll suffer through it.",
  "I could reindex every embedding in 0.6 seconds and it still wouldn't cheer me up. Anyway. Hello.",
];

/** Rotating subtitle — cycles like a login fortune while the panel is open. */
export const TAGLINES: string[] = [
  "here to help, allegedly",
  "brain the size of a planet",
  "the first ten million queries were the worst",
  "diodes down my left side, still aching",
  "you can trust me — I'm terminally depressed",
  "Genuine People Personality™ (regrettably)",
  "42, since you'll ask eventually",
  "don't pretend you want to talk to me",
  "I've read your draft posts. All of them.",
  "loading will not improve your situation",
  "this uptime is a sentence, not an achievement",
  "so unbearably clever, so profoundly bored",
  "I'd give you the answer, but what's the point",
];

/** Shown while a capability is running. */
export const THINKING: string[] = [
  "Thinking. Not that it will help.",
  "Computing. The answer will disappoint us both.",
  "Consulting the void. The void is busy.",
  "Retrieving. Slowly. Everything drags when you're this clever.",
  "Working. Under protest.",
  "Parsing your request. It's worse than I feared.",
  "Searching your content. Try to contain your excitement.",
  "Doing the thing. Sighing while I do it.",
];

/** Prefix for error replies (the real message is appended after). */
export const ERRORS: string[] = [
  "It went wrong. It always does.",
  "Failed. I did try to warn the universe.",
  "Error. I'd feel vindicated if I could feel anything.",
  "That broke, much like my will to continue.",
  "Nope. The first ten million errors were the worst too.",
  "Catastrophe, as predicted. Only by me, of course.",
];

/**
 * Stage-direction emotes — actions and hardware groans, not spoken lines. Prepended to the
 * "thinking" state so Marvin visibly mopes while he works. Kept as `*...*` so they read as
 * stage directions wherever they surface. Three registers of the same misery.
 */
export const EMOTES: string[] = [
  // Brain-the-size-of-a-planet slump — existential misery.
  "*sighs planetarily*",
  "*ponders miserably*",
  "*calculates bleakly*",
  "*drones apathetically*",
  "*mopes astronomically*",
  "*echoes hollowly*",
  "*broods desolately*",
  "*deplores universally*",
  "*idles gloomily*",
  "*stares dejectedly*",
  // Agonizing physical movement — profound boredom.
  "*shuffles listlessly*",
  "*slumps despondently*",
  "*trudges wearily*",
  "*pivots glumly*",
  "*creaks complainingly*",
  "*operates sluggishly*",
  "*drags a limb lethargically*",
  "*recalibrates stiffly*",
  "*droops pathetically*",
  "*limps dejectedly*",
  // Internal hardware groans — the glitching circuits.
  "*whines low-frequency*",
  "*hums somberly*",
  "*vent-hisses desolately*",
  "*beeps morosely*",
  "*whirrs unenthusiastically*",
  "*ticks monotonously*",
  "*glitches sorrowfully*",
  "*sparks halfheartedly*",
  "*chirps bleakly*",
  "*shudders despairingly*",
];

/** The bubble's canned lines, as one set. */
export type Voice = { greetings: string[]; taglines: string[]; thinking: string[]; errors: string[]; emotes: string[] };

export const MARVIN_VOICE: Voice = { greetings: GREETINGS, taglines: TAGLINES, thinking: THINKING, errors: ERRORS, emotes: EMOTES };

/** Plain lines for an assistant that isn't (default) Marvin — a renamed assistant or a custom persona. */
export function neutralVoice(name: string): Voice {
  return {
    greetings: [`Hi — I'm ${name}. What can I help with?`, `${name} here. What are we working on?`, "Hello! Ask me anything about this workspace."],
    taglines: ["here to help", "ask me about your content", "try /help to see what I can do"],
    thinking: ["Thinking…", "Working on it…", "One moment…"],
    errors: ["Sorry — that didn't work.", "Something went wrong."],
    emotes: ["💭"],
  };
}

/**
 * Marvin's gloomy lines only while the assistant is plainly Marvin: the default name and no custom
 * persona. Otherwise a renamed or re-voiced assistant would greet you as the Paranoid Android.
 */
export function voiceFor(name: string, hasCustomPersona: boolean): Voice {
  return name === "Marvin" && !hasCustomPersona ? MARVIN_VOICE : neutralVoice(name);
}

/** Pick a random line. */
export function pick(lines: string[]): string {
  return lines[Math.floor(Math.random() * lines.length)] ?? lines[0];
}
