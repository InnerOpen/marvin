/**
 * The Approvals page's "Recently decided" list: how one settled approval reads. Free of the DOM and of runtime imports
 * so it runs under `node --test` (approvalHistory.test.mjs).
 */

const STATUS_WORDS: Record<string, string> = { approved: "Approved", denied: "Denied", expired: "Expired", stale: "Stale: the entry changed" };

/** "Approved: Dusk" for an approval that picked a choice, "Denied", "Expired"…; the raw status when it is one we don't know. */
export function decisionLabel(status: string, choice?: string | null): string {
  const word = STATUS_WORDS[status] ?? status;
  return choice && status === "approved" ? `${word}: ${choice}` : word;
}

/** Who and how: "Jared" for a person, "no one" for an approval that expired or went stale on its own. */
export function deciderLabel(decidedByName?: string | null): string {
  return decidedByName?.trim() || "no one";
}

/** The first line of a question, for a one-line row: the full text stays on the row's title. */
export function firstLine(message: string): string {
  return (message ?? "").split("\n")[0].trim();
}
