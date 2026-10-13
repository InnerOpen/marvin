// What a failed save says, for the banner a server-rendered form shows above itself
// (components/SaveErrorBanner.astro). Kept out of the pages so it can be tested with plain
// `node --test` (see saveError.test.mjs).

export type SaveError = {
  /** One line: what went wrong. */
  message: string;
  /** Each thing to fix, when the API listed them (the publish gate's unmet requirements, invalid fields). */
  issues: string[];
};

const GENERIC = "Couldn't save your changes.";

/** The parsed JSON body of a failed API call: the SDK keeps it as a string, fetchApi as an object. */
function errorBody(error: unknown): unknown {
  const e = error as { responseBody?: unknown; body?: unknown } | null;
  const raw = e?.responseBody ?? e?.body;
  if (typeof raw !== "string") return raw;
  try {
    return JSON.parse(raw);
  } catch {
    return undefined;
  }
}

/** A FastAPI validation error's field path, without the leading "body". */
function fieldPath(loc: unknown): string {
  if (!Array.isArray(loc)) return "";
  return loc.filter((part, i) => !(i === 0 && part === "body")).join(".");
}

function issueText(issue: unknown): string {
  const message = (issue as { message?: unknown } | null)?.message;
  if (typeof message === "string") return message;
  return typeof issue === "string" ? issue : JSON.stringify(issue);
}

function fromDetail(detail: unknown): SaveError | null {
  if (typeof detail === "string" && detail.trim()) return { message: detail, issues: [] };
  if (Array.isArray(detail)) {
    const issues = detail.map((d) => {
      const path = fieldPath(d?.loc);
      const msg = typeof d?.msg === "string" ? d.msg : JSON.stringify(d);
      return path ? `${path}: ${msg}` : msg;
    });
    return { message: "Some fields aren't valid.", issues };
  }
  if (detail && typeof detail === "object") {
    // The publish gate: {message: "Cannot publish — 2 requirement(s) unmet.", issues: [...]}. Issues are
    // strings, or {message, where, …} objects (a workflow definition's structural errors).
    const { message, issues } = detail as { message?: unknown; issues?: unknown };
    const list = Array.isArray(issues) ? issues.map(issueText) : [];
    if (typeof message === "string" || list.length) {
      return { message: typeof message === "string" && message ? message : GENERIC, issues: list };
    }
  }
  return null;
}

/** A readable account of why a save failed, from whatever the API client threw. */
export function describeSaveError(error: unknown): SaveError {
  const body = errorBody(error) as { detail?: unknown } | undefined;
  const described = body && typeof body === "object" ? fromDetail(body.detail) : null;
  if (described) return described;
  const e = error as { statusCode?: unknown; status?: unknown } | null;
  const status = e?.statusCode ?? e?.status;
  if (status === 401 || status === 403) {
    return {
      message: "Your session has expired or you don't have permission to do this. Sign in again and retry.",
      issues: [],
    };
  }
  // The SDK's own message repeats the method, URL and raw body; only its first line reads well.
  const text = error instanceof Error ? error.message.split("\n")[0].trim() : "";
  return { message: text || GENERIC, issues: [] };
}
