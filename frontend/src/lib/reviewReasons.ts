// Why an entry is waiting in Needs review — a flagged form submission's reasons
// (`metadata_json.submission.review_reasons`) and those a workflow added with its `request_review` step
// (`metadata_json.review_reasons`, e.g. "Buttondown refused the signup …"). Pure, so it's tested with
// plain `node --test` (see reviewReasons.test.mjs).

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string" && v.trim() !== "") : [];
}

/** The entry's review reasons, submission ones first, each listed once. */
export function reviewReasons(metadata: unknown): string[] {
  if (!metadata || typeof metadata !== "object") return [];
  const meta = metadata as Record<string, unknown>;
  const submission =
    meta.submission && typeof meta.submission === "object" ? (meta.submission as Record<string, unknown>) : {};
  return [...new Set([...strings(submission.review_reasons), ...strings(meta.review_reasons)])];
}
