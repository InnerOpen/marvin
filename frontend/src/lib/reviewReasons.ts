// Why an entry is waiting in Needs review — a flagged form submission's reasons
// (`metadata_json.submission.review_reasons`), those a workflow added with its `request_review` step
// (`metadata_json.review_reasons`, e.g. "Buttondown refused the signup …"), and the integration
// failures whose error policy sent it to review (`metadata_json.integration_error.<slug>`, e.g.
// "Square · invalid — price must be positive"). Pure, so it's tested with plain `node --test`
// (see reviewReasons.test.mjs).

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string" && v.trim() !== "") : [];
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

/** One line per integration whose failure sent the entry to review: "Square · invalid — <message>". */
export function integrationErrors(metadata: unknown): string[] {
  return Object.entries(record(record(metadata).integration_error)).flatMap(([slug, value]) => {
    const note = record(value);
    const who = typeof note.provider_name === "string" && note.provider_name ? note.provider_name : slug;
    const code = typeof note.code === "string" && note.code ? ` · ${note.code}` : "";
    const message = typeof note.message === "string" && note.message.trim() ? ` — ${note.message.trim()}` : "";
    return code || message ? [`${who}${code}${message}`] : [];
  });
}

/** The entry's review reasons, submission ones first, then a workflow's, then integration failures — each listed once. */
export function reviewReasons(metadata: unknown): string[] {
  const meta = record(metadata);
  const submission = record(meta.submission);
  return [
    ...new Set([...strings(submission.review_reasons), ...strings(meta.review_reasons), ...integrationErrors(meta)]),
  ];
}
