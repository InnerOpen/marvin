/**
 * The greeting the bubble is showing, kept so the first message after it can say which line it answers.
 *
 * The bubble picks its greeting in the browser (Marvin.astro, `pick(voice.greetings)`), so the agent never
 * saw it — a "yes" or "what do you mean?" to it meant nothing. The first message of a new conversation
 * carries the line (`greeting` on the run request); the server checks it is one of that agent's configured
 * lines and puts it in as the assistant's opening turn. Only a new conversation gets one: a rehydrated or
 * continuing thread already has its own turns.
 *
 * DOM-free (pending.test-style) so it runs under `node --test`.
 */

let shown: { text: string; agent: string } | null = null;

/** The bubble showed `text` while talking to `agent`. */
export function noteGreeting(text: string, agent: string): void {
  shown = { text, agent };
}

/** The conversation the greeting opened is over (Clear) or never will be (a restored transcript). */
export function dropGreeting(): void {
  shown = null;
}

/**
 * The greeting to send with a message to `agent`, once: whatever the message, it answers the greeting
 * from here on. `undefined` when none was shown, it was another agent's, or the conversation already
 * has a thread (`continuing`).
 */
export function takeGreeting(agent: string, continuing: boolean): string | undefined {
  const taken = shown;
  shown = null;
  return taken && !continuing && taken.agent === agent ? taken.text : undefined;
}
