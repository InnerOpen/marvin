// Audience › Submissions (audience.ts): the sidebar fold, a row, the status words, actions, filters and the empty state.
// Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  actionButtons,
  dayBound,
  hasSubscriberFilters,
  historyLines,
  integrationNote,
  NO_SUBSCRIBER_FILTERS,
  openSubscriberHref,
  parseSubscriberFilters,
  signupFormOptions,
  statusTiles,
  subscriberActions,
  subscriberApiQuery,
  subscriberBadge,
  subscriberFiltersToQuery,
  subscriberRow,
  subscribersEmptyNotice,
  subscribersNav,
  apiQuery,
  emptyNotice,
  excerptOf,
  fieldText,
  filtersToQuery,
  formOfPath,
  formOptions,
  hasFilters,
  isSubmissionsPath,
  openAsEntryHref,
  parseFilters,
  showAudienceGroup,
  sourceLines,
  stateBadge,
  submissionRow,
  submissionsNav,
  submissionsPath,
  verdictText,
  whoOf,
} from "./audience.ts";

const form = (slug, extra = {}) => ({ slug, name: slug.toUpperCase(), icon: null, new: 0, ...extra });
const summary = (forms, extra = {}) => ({
  submissions: { show: forms.length > 0, new: forms.reduce((n, f) => n + f.new, 0), forms },
  signups: { show: false, forms: [], pending: 0, confirmed: 0, unsubscribed: 0, problem: 0, waiting: 0, integrations: [] },
  can: { act: true, fullIp: false },
  ...extra,
});
const sub = (fields, extra = {}) => ({
  id: "s1",
  form: form("contact", { name: "Contact", icon: "💌" }),
  title: "A title",
  state: "new",
  status: "inbox",
  fields,
  verdict: { flagged: false, reasons: [] },
  source: {},
  createdAt: "2026-10-20T10:00:00Z",
  path: "/workspace/entries/abc",
  ...extra,
});
const f = (key, value, type = "text", label = key) => ({ key, label, type, value });

describe("the sidebar fold", () => {
  test("nothing is drawn until a form sends its submissions to the Audience", () => {
    assert.equal(submissionsNav(null), null);
    assert.equal(submissionsNav(undefined), null);
    assert.equal(submissionsNav(summary([])), null);
    assert.equal(submissionsNav({ ...summary([form("a")]), submissions: { show: false, new: 0, forms: [form("a")] } }), null);
  });

  test("one child per form with its name, icon and waiting count; the row carries the total", () => {
    const nav = submissionsNav(summary([form("contact", { name: "Contact", icon: "💌", new: 12 }), form("workshop", { name: "Workshop enquiry", new: 0 })]));
    assert.equal(nav.label, "Submissions");
    assert.equal(nav.href, "/workspace/audience/submissions");
    assert.equal(nav.badge, "12");
    assert.equal(nav.badgeLabel, "12 new");
    assert.deepEqual(
      nav.children.map((c) => [c.slug, c.href, c.label, c.icon, c.badge]),
      [
        ["contact", "/workspace/audience/submissions/contact", "Contact", "💌", "12"],
        ["workshop", "/workspace/audience/submissions/workshop", "Workshop enquiry", "✉️", ""], // no icon: the envelope; no count: no badge
      ],
    );
  });

  test("a count past 99 reads 99+, and a slug is escaped in the link", () => {
    const nav = submissionsNav(summary([form("a b", { new: 250 })]));
    assert.equal(nav.badge, "99+");
    assert.equal(nav.children[0].href, "/workspace/audience/submissions/a%20b");
  });

  test("the Audience heading is drawn when Social or Submissions has something", () => {
    assert.equal(showAudienceGroup([null, null]), false);
    assert.equal(showAudienceGroup([{ label: "Social" }, null]), true);
    assert.equal(showAudienceGroup([null, { label: "Submissions" }]), true);
    assert.equal(showAudienceGroup([undefined]), false);
  });

  test("paths: a form's page, the all-forms page, and which paths keep the fold open", () => {
    assert.equal(submissionsPath(), "/workspace/audience/submissions");
    assert.equal(submissionsPath("contact"), "/workspace/audience/submissions/contact");
    assert.equal(isSubmissionsPath("/workspace/audience/submissions"), true);
    assert.equal(isSubmissionsPath("/workspace/audience/submissions/contact"), true);
    assert.equal(isSubmissionsPath("/workspace/audience/submissionsx"), false);
    assert.equal(isSubmissionsPath("/workspace/social"), false);
    assert.equal(formOfPath("/workspace/audience/submissions/contact"), "contact");
    assert.equal(formOfPath("/workspace/audience/submissions/a%20b"), "a b");
    assert.equal(formOfPath("/workspace/audience/submissions"), null);
  });

  test("the form filter's options are the forms", () => {
    assert.deepEqual(formOptions(summary([form("a", { name: "A" })])), [{ value: "a", label: "A" }]);
    assert.deepEqual(formOptions(null), []);
  });
});

describe("a row", () => {
  test("who is a name field, else an email, else the title", () => {
    assert.equal(whoOf(sub([f("email", "ann@x.test"), f("name", "Ann")])), "Ann");
    assert.equal(whoOf(sub([f("your_name", "Bo", "text", "Your name")])), "Bo");
    assert.equal(whoOf(sub([f("who", "Cy", "text", "Full name")])), "Cy"); // the label says name
    assert.equal(whoOf(sub([f("email", "ann@x.test"), f("message", "hi", "textarea")])), "ann@x.test");
    assert.equal(whoOf(sub([f("contact", "dee@x.test", "email")])), "dee@x.test");
    assert.equal(whoOf(sub([f("message", "hi", "textarea")])), "A title");
    assert.equal(whoOf(sub([], { title: "  " })), "Someone");
    assert.equal(whoOf(sub([f("name", "")])), "A title"); // a blank name is no name
  });

  test("the excerpt is the long text, else the first other text, not the name or email", () => {
    assert.equal(excerptOf(sub([f("name", "Ann"), f("subject", "Hi"), f("message", "Please call me back", "textarea")])), "Please call me back");
    assert.equal(excerptOf(sub([f("name", "Ann"), f("email", "a@x.test"), f("subject", "Pricing")])), "Pricing");
    assert.equal(excerptOf(sub([f("name", "Ann"), f("email", "a@x.test")])), "a@x.test"); // only a name and an email: the email
    assert.equal(excerptOf(sub([f("email", "a@x.test")])), ""); // the email is already the "who"
    assert.equal(excerptOf(sub([])), "");
    assert.ok(excerptOf(sub([f("message", "word ".repeat(100), "textarea")]), 40).endsWith("…"));
    assert.equal(excerptOf(sub([f("message", "line one\n\n   line two", "textarea")])), "line one line two");
  });

  test("values read as text: lists joined, booleans yes or no, blanks empty", () => {
    assert.equal(fieldText(["a", "b"]), "a, b");
    assert.equal(fieldText(true), "Yes");
    assert.equal(fieldText(false), "No");
    assert.equal(fieldText(null), "");
    assert.equal(fieldText(3), "3");
    assert.equal(fieldText("  hi "), "hi");
    assert.equal(fieldText({ a: 1 }), '{"a":1}');
  });

  test("the status badge: New, Suspicious (reasons as its tooltip), Handled", () => {
    assert.deepEqual(stateBadge("new").label, "New");
    assert.equal(stateBadge("new").tone, "new");
    assert.equal(stateBadge("suspicious").label, "Suspicious");
    assert.equal(stateBadge("suspicious").tone, "warn");
    assert.equal(stateBadge("suspicious", ["blocked_domain:x.com", "link spam"]).title, "blocked_domain:x.com; link spam");
    assert.equal(stateBadge("handled").label, "Handled");
    assert.equal(stateBadge("handled").tone, "muted");
    assert.equal(stateBadge("weird").label, "weird");
  });

  test("a row: who, excerpt, form, icon, when, badge; new and suspicious are unread, handled isn't", () => {
    const row = submissionRow(sub([f("name", "Ann"), f("message", "Hello", "textarea")]));
    assert.deepEqual(
      { who: row.who, text: row.text, form: row.form, icon: row.formIcon, at: row.at, badge: row.badge.label, unread: row.unread },
      { who: "Ann", text: "Hello", form: "Contact", icon: "💌", at: "2026-10-20T10:00:00Z", badge: "New", unread: true },
    );
    assert.equal(submissionRow(sub([], { state: "suspicious" })).unread, true);
    assert.equal(submissionRow(sub([], { state: "handled" })).unread, false);
    assert.equal(submissionRow(sub([], { form: { slug: "x", name: "X", new: 0 } })).formIcon, "✉️");
  });
});

describe("the open submission", () => {
  const keys = (item, can = { act: true }) => actionButtons(item, can).map((b) => b.key + ":" + b.label);

  test("New offers Mark handled and Delete", () => {
    assert.deepEqual(keys({ state: "new" }), ["handled:Mark handled", "delete:Delete"]);
  });
  test("Suspicious offers Not spam first, then Mark handled and Delete", () => {
    assert.deepEqual(keys({ state: "suspicious" }), ["reopen:Not spam", "handled:Mark handled", "delete:Delete"]);
  });
  test("Handled offers Reopen and Delete", () => {
    assert.deepEqual(keys({ state: "handled" }), ["reopen:Reopen", "delete:Delete"]);
  });
  test("Delete is the destructive one; a caller who may not act gets none", () => {
    assert.equal(actionButtons({ state: "new" }, { act: true }).find((b) => b.key === "delete").destructive, true);
    assert.deepEqual(actionButtons({ state: "new" }, { act: false }), []);
    assert.deepEqual(actionButtons({ state: "new" }, {}), []);
    assert.deepEqual(actionButtons({ state: "new" }, undefined), []);
  });

  test("Open as entry comes back to the page it was opened from", () => {
    assert.equal(openAsEntryHref({ path: "/workspace/entries/abc" }, "/workspace/audience/submissions/contact?status=new"), "/workspace/entries/abc?return=%2Fworkspace%2Faudience%2Fsubmissions%2Fcontact%3Fstatus%3Dnew");
    assert.equal(openAsEntryHref({ path: "/workspace/entries/abc" }, "https://evil.test/"), "/workspace/entries/abc"); // only same-site paths
  });

  test("the verdict in words", () => {
    assert.deepEqual(verdictText({ state: "new", verdict: { flagged: false, reasons: [] } }), { tone: "good", text: "Passed the spam checks" });
    assert.equal(verdictText({ state: "suspicious", verdict: { flagged: true, reasons: ["blocked_domain:x.com"] } }).text, "Held for review: blocked_domain:x.com");
    assert.equal(verdictText({ state: "new", verdict: { flagged: true, reasons: ["a", "b"] } }).text, "Was held for review: a; b"); // cleared since
    assert.equal(verdictText({ state: "suspicious", verdict: { flagged: true, reasons: [] } }).tone, "warn");
  });

  test("the source shows only what was recorded; the IP says when it is partly hidden", () => {
    assert.deepEqual(sourceLines({ source: {} }), []);
    assert.deepEqual(sourceLines({ source: { ip: "203.0.113.x", ipMasked: true, referrer: "https://s.test/c", userAgent: "UA", count: 3 } }), [
      { label: "IP (partly hidden)", value: "203.0.113.x" },
      { label: "From page", value: "https://s.test/c" },
      { label: "Browser", value: "UA" },
      { label: "Sent", value: "3 times by the same person" },
    ]);
    assert.equal(sourceLines({ source: { ip: "203.0.113.7", ipMasked: false } })[0].label, "IP address");
    assert.deepEqual(sourceLines({ source: { count: 1 } }), []);
  });
});

describe("filters", () => {
  test("read from the URL: a status must be one of the three; a form's own page fixes the form", () => {
    assert.deepEqual(parseFilters(new URLSearchParams("form=contact&status=new&q=%20hello%20")), { form: "contact", status: "new", q: "hello" });
    assert.deepEqual(parseFilters(new URLSearchParams("status=bogus")), { form: "", status: "", q: "" });
    assert.equal(parseFilters(new URLSearchParams("form=other"), "contact").form, "contact");
    assert.equal(parseFilters(new URLSearchParams(`q=${"x".repeat(300)}`)).q.length, 200);
  });

  test("the page's query string leaves out what is empty, and the form when it is in the path", () => {
    assert.equal(filtersToQuery({ form: "", status: "", q: "" }), "");
    assert.equal(filtersToQuery({ form: "contact", status: "handled", q: "a b" }), "?form=contact&status=handled&q=a+b");
    assert.equal(filtersToQuery({ form: "contact", status: "new", q: "" }, true), "?status=new");
  });

  test("the API's query: filters, the page size and the offset", () => {
    assert.equal(apiQuery({ form: "", status: "", q: "" }), "limit=50");
    assert.equal(apiQuery({ form: "contact", status: "suspicious", q: "x" }, 50), "form=contact&status=suspicious&q=x&limit=50&offset=50");
  });

  test("hasFilters: a form's own page doesn't count its form", () => {
    assert.equal(hasFilters({ form: "", status: "", q: "" }), false);
    assert.equal(hasFilters({ form: "contact", status: "", q: "" }), true);
    assert.equal(hasFilters({ form: "contact", status: "", q: "" }, true), false);
    assert.equal(hasFilters({ form: "contact", status: "new", q: "" }, true), true);
  });
});

describe("the empty state", () => {
  test("a filter that matches nothing", () => {
    assert.equal(emptyNotice(summary([form("a")]), true).title, "Nothing matches these filters");
  });
  test("no form at all says how one appears", () => {
    const notice = emptyNotice(summary([]), false);
    assert.match(notice.title, /No form/);
    assert.equal(notice.link.href, "/workspace/entry-types");
  });
  test("a form with no submissions yet, and every form with none", () => {
    assert.equal(emptyNotice(summary([form("contact", { name: "Contact" })]), false, form("contact", { name: "Contact" })).title, "No Contact submissions yet");
    assert.equal(emptyNotice(summary([form("contact")]), false).title, "Nothing here yet");
  });
});

// ── Subscribers ───────────────────────────────────────────────────────────────────────────────────────────────────────

const signups = (extra = {}) => ({
  show: true,
  forms: [form("newsletter", { name: "Newsletter", new: 4 })],
  pending: 3,
  confirmed: 10,
  unsubscribed: 2,
  problem: 1,
  waiting: 4,
  integrations: [],
  ...extra,
});
const subscriber = (extra = {}) => ({
  id: "u1",
  form: form("newsletter", { name: "Newsletter", icon: null }),
  email: "ann@x.test",
  name: "Ann Abel",
  title: "Newsletter from ann",
  status: "pending",
  entryStatus: "inbox",
  reviewReasons: [],
  reason: null,
  signedUpAt: "2026-10-20T10:00:00Z",
  path: "/workspace/entries/u1",
  ...extra,
});

describe("the sidebar's Subscribers item", () => {
  test("nothing is drawn until a form is a signup form", () => {
    assert.equal(subscribersNav(null), null);
    assert.equal(subscribersNav(undefined), null);
    assert.equal(subscribersNav(summary([])), null);
    assert.equal(subscribersNav(summary([], { signups: signups({ show: false }) })), null);
  });

  test("a link to the page with pending plus problems as its badge", () => {
    const nav = subscribersNav(summary([], { signups: signups() }));
    assert.deepEqual(nav, { label: "Subscribers", href: "/workspace/audience/subscribers", badge: "4", badgeLabel: "4 pending or needing a look" });
  });

  test("no badge at zero, 99+ past 99, and the sum when the API sent no total", () => {
    assert.equal(subscribersNav(summary([], { signups: signups({ pending: 0, problem: 0, waiting: 0 }) })).badge, "");
    assert.equal(subscribersNav(summary([], { signups: signups({ waiting: 250 }) })).badge, "99+");
    assert.equal(subscribersNav(summary([], { signups: { show: true, forms: [], pending: 2, problem: 1 } })).badge, "3");
  });

  test("it alone draws the Audience heading", () => {
    assert.equal(showAudienceGroup([null, null, subscribersNav(summary([], { signups: signups() }))]), true);
    assert.equal(showAudienceGroup([null, null, null]), false);
  });
});

describe("a subscriber row", () => {
  test("a name leads with the email beside it; without one the email leads", () => {
    const named = subscriberRow(subscriber());
    assert.equal(named.who, "Ann Abel");
    assert.equal(named.email, "ann@x.test");
    const bare = subscriberRow(subscriber({ name: null }));
    assert.equal(bare.who, "ann@x.test");
    assert.equal(bare.email, "");
    assert.equal(subscriberRow(subscriber({ name: null, email: null })).who, "Newsletter from ann");
    assert.equal(subscriberRow(subscriber({ name: " ", email: "", title: "" })).who, "Someone");
  });

  test("the form, when it arrived and a fallback icon", () => {
    const r = subscriberRow(subscriber());
    assert.equal(r.form, "Newsletter");
    assert.equal(r.formIcon, "📬");
    assert.equal(r.at, "2026-10-20T10:00:00Z");
    assert.equal(subscriberRow(subscriber({ form: form("n", { icon: "🎟" }) })).formIcon, "🎟");
  });

  test("pending and a problem are drawn as waiting; confirmed and unsubscribed are not", () => {
    const unread = (status) => subscriberRow(subscriber({ status })).unread;
    assert.deepEqual(["pending", "confirmed", "unsubscribed", "problem"].map(unread), [true, false, false, true]);
  });

  test("a problem shows its reason on the row, others never do", () => {
    assert.equal(subscriberRow(subscriber({ status: "problem", reason: " Buttondown · refused " })).reason, "Buttondown · refused");
    assert.equal(subscriberRow(subscriber({ status: "confirmed", reason: "old" })).reason, "");
  });
});

describe("the status words", () => {
  test("each status has its word and tone", () => {
    assert.deepEqual(
      ["pending", "confirmed", "unsubscribed", "problem"].map((s) => [subscriberBadge(s).label, subscriberBadge(s).tone]),
      [["Pending", "new"], ["Confirmed", "good"], ["Unsubscribed", "muted"], ["Needs a look", "warn"]],
    );
  });

  test("a problem's tooltip is its reason; an unknown status is shown as it is", () => {
    assert.equal(subscriberBadge("problem", "Spam firewall").title, "Spam firewall");
    assert.match(subscriberBadge("problem").title, /refused/);
    assert.deepEqual(subscriberBadge("weird"), { label: "weird", tone: "neutral" });
    assert.equal(subscriberBadge("").label, "Unknown");
  });

  test("the counts strip has a tile per status, in order, with the active one marked", () => {
    const tiles = statusTiles({ pending: 3, confirmed: 10, unsubscribed: 2, problem: 1 }, "problem");
    assert.deepEqual(tiles.map((t) => [t.value, t.count, t.active]), [["pending", 3, false], ["confirmed", 10, false], ["unsubscribed", 2, false], ["problem", 1, true]]);
    assert.deepEqual(statusTiles(null).map((t) => t.count), [0, 0, 0, 0]);
    assert.equal(statusTiles({ pending: -2 })[0].count, 0);
  });
});

describe("subscriber filters", () => {
  test("parse keeps a known status, a plain day and trims the search", () => {
    const f = parseSubscriberFilters(new URLSearchParams("status=problem&q=%20ann%20&form=news&from=2026-10-01&to=2026-10-31"));
    assert.deepEqual(f, { form: "news", status: "problem", q: "ann", from: "2026-10-01", to: "2026-10-31" });
    assert.deepEqual(parseSubscriberFilters(new URLSearchParams("status=bogus&from=yesterday&to=2026-13")), NO_SUBSCRIBER_FILTERS);
  });

  test("the page query keeps only what is set, and round-trips", () => {
    assert.equal(subscriberFiltersToQuery(NO_SUBSCRIBER_FILTERS), "");
    const f = { form: "news", status: "pending", q: "a b", from: "2026-10-01", to: "" };
    const text = subscriberFiltersToQuery(f);
    assert.equal(text, "?form=news&status=pending&q=a+b&from=2026-10-01");
    assert.deepEqual(parseSubscriberFilters(new URLSearchParams(text.slice(1))), f);
  });

  test("the API query pages, and turns a day into the start and end of that day", () => {
    const q = new URLSearchParams(subscriberApiQuery({ form: "news", status: "problem", q: "x", from: "2026-10-01", to: "2026-10-02" }, 50, 25));
    assert.equal(q.get("form"), "news");
    assert.equal(q.get("status"), "problem");
    assert.equal(q.get("q"), "x");
    assert.equal(q.get("limit"), "25");
    assert.equal(q.get("offset"), "50");
    const since = new Date(q.get("since"));
    const until = new Date(q.get("until"));
    assert.ok(since < until);
    const hours = (until - since) / 3_600_000;
    assert.ok(hours > 46 && hours < 49, `two whole days, DST aside: ${hours}`); // the start of the 1st to the end of the 2nd
    assert.equal(new URLSearchParams(subscriberApiQuery(NO_SUBSCRIBER_FILTERS)).get("offset"), null);
    assert.equal(new URLSearchParams(subscriberApiQuery(NO_SUBSCRIBER_FILTERS)).get("since"), null);
  });

  test("a day bound is null for anything that isn't a day", () => {
    assert.equal(dayBound("", false), null);
    assert.equal(dayBound("soon", true), null);
    assert.ok(new Date(dayBound("2026-10-05", true)) > new Date(dayBound("2026-10-05", false)));
  });

  test("hasSubscriberFilters sees each one", () => {
    assert.equal(hasSubscriberFilters(NO_SUBSCRIBER_FILTERS), false);
    for (const k of ["form", "status", "q", "from", "to"]) assert.equal(hasSubscriberFilters({ ...NO_SUBSCRIBER_FILTERS, [k]: k === "status" ? "pending" : "2026-10-05" }), true);
  });

  test("the form filter offers each signup form", () => {
    assert.deepEqual(signupFormOptions(summary([], { signups: signups() })), [{ value: "newsletter", label: "Newsletter" }]);
    assert.deepEqual(signupFormOptions(null), []);
  });
});

describe("what the page says about the integration", () => {
  test("a connected integration is named as the one that subscribes and unsubscribes", () => {
    const note = integrationNote([{ slug: "buttondown", name: "Buttondown", provider: "buttondown" }]);
    assert.equal(note.kind, "handled");
    assert.match(note.text, /Buttondown handles subscribing and unsubscribing/);
    assert.match(note.text, /can't unsubscribe someone from this page/);
  });

  test("several are listed", () => {
    const note = integrationNote([{ slug: "a", name: "A", provider: "a" }, { slug: "b", name: "B", provider: "b" }]);
    assert.match(note.text, /A, B handles/);
  });

  test("none connected is a hint to connect one, and the signups are still listed", () => {
    for (const none of [[], null, undefined]) {
      const note = integrationNote(none);
      assert.equal(note.kind, "hint");
      assert.match(note.text, /No mailing-list integration is connected/);
      assert.match(note.text, /still collected and listed here/);
      assert.equal(note.link.href, "/workspace/settings/integrations");
    }
  });
});

describe("the open subscriber", () => {
  test("only Delete, for a caller who may act, and it says it does not unsubscribe", () => {
    const [del, ...rest] = subscriberActions({ act: true });
    assert.deepEqual(rest, []);
    assert.equal(del.key, "delete");
    assert.equal(del.destructive, true);
    assert.match(del.hint, /does not unsubscribe/);
    assert.deepEqual(subscriberActions({ act: false }), []);
    assert.deepEqual(subscriberActions(undefined), []);
  });

  test("Open as entry returns to the page with its filters", () => {
    const href = openSubscriberHref(subscriber(), "/workspace/audience/subscribers?status=pending");
    assert.equal(href, "/workspace/entries/u1?return=%2Fworkspace%2Faudience%2Fsubscribers%3Fstatus%3Dpending");
  });

  test("the history keeps only complete lines, in the order given (newest first)", () => {
    assert.deepEqual(historyLines({ history: [{ label: "Confirmed", at: "2026-10-20T11:00:00Z" }, { label: "", at: "x" }, { label: "Signed up", at: "2026-10-20T10:00:00Z" }] }).map((h) => h.label), ["Confirmed", "Signed up"]);
    assert.deepEqual(historyLines({}), []);
  });
});

describe("the empty states", () => {
  test("a filter that matches nothing, no signup form yet, and a form with no signups", () => {
    assert.match(subscribersEmptyNotice(summary([], { signups: signups() }), true).title, /Nothing matches/);
    const none = subscribersEmptyNotice(summary([]), false);
    assert.equal(none.title, "No signup form yet");
    assert.equal(none.link.href, "/workspace/entry-types");
    assert.equal(subscribersEmptyNotice(summary([], { signups: signups() }), false).title, "No signups yet");
    assert.equal(subscribersEmptyNotice(null, false).title, "No signups yet");
  });
});
