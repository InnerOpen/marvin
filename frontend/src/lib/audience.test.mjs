// Audience › Submissions (audience.ts): the sidebar fold, a row, the status words, actions, filters and the empty state.
// Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  actionButtons,
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
  signups: { show: false, forms: [] },
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
