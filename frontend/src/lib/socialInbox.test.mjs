// The Social inbox page's pure logic (socialInbox.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  actionButtons,
  apiQuery,
  authorLabel,
  confirmText,
  emptyNotice,
  errorMessage,
  excerpt,
  filtersToQuery,
  hasFilters,
  integrationOptions,
  kindLabel,
  NO_FILTERS,
  newBadgeText,
  openHref,
  parseFilters,
  replyAgainText,
  replyBadge,
  replyForm,
  replyText,
  statusBadge,
  timeAgo,
} from "./socialInbox.ts";

const NOW = new Date("2026-10-20T12:00:00Z");
const ALL = ["reply", "like", "hide", "delete", "message"];
const ADMIN = {
  seen: true,
  like: true,
  hide: true,
  rule: true,
  rules: true,
  publish: true,
  auto_reply: true,
  reply: true,
  delete: true,
  message: true,
};
const EDITOR = { seen: true, like: true, hide: true, rule: true, reply: false, delete: false, message: false };

describe("a row", () => {
  test("the author is a handle with an @, else a name, else an id", () => {
    assert.equal(authorLabel({ handle: "alice", name: "Alice" }), "@alice");
    assert.equal(authorLabel({ handle: "@bob.bsky.social" }), "@bob.bsky.social");
    assert.equal(authorLabel({ handle: " ", name: "Carol" }), "Carol");
    assert.equal(authorLabel({ id: "u-1" }), "u-1");
    assert.equal(authorLabel({}), "Someone");
    assert.equal(authorLabel(undefined), "Someone");
  });

  test("an excerpt is one line, cut at a word with an ellipsis, and short text is left alone", () => {
    assert.equal(excerpt("  What is\n the   price? "), "What is the price?");
    const long = `${"word ".repeat(60)}end`;
    const cut = excerpt(long, 50);
    assert.ok(cut.endsWith("…") && cut.length <= 51 && !cut.includes("wor…"), cut);
    assert.equal(excerpt("x".repeat(200), 20), `${"x".repeat(20)}…`); // no space to cut at: cut at the limit
    assert.equal(excerpt("", 10), "");
    assert.equal(
      excerpt("Great, thanks, really, truly, fine. And so on and on and on", 28),
      "Great, thanks, really, truly…",
    );
  });

  test("times are relative up to a month, then a date; a bad or missing time is empty", () => {
    const ago = (ms) => new Date(NOW.getTime() - ms).toISOString();
    assert.equal(timeAgo(ago(20_000), NOW), "just now");
    assert.equal(timeAgo(ago(5 * 60_000), NOW), "5 min ago");
    assert.equal(timeAgo(ago(3 * 3_600_000), NOW), "3 h ago");
    assert.equal(timeAgo(ago(2 * 86_400_000), NOW), "2 d ago");
    assert.equal(timeAgo(ago(40 * 86_400_000), NOW), "2026-09-10");
    assert.equal(timeAgo(new Date(NOW.getTime() + 60_000).toISOString(), NOW), "just now");
    assert.equal(timeAgo("nonsense", NOW), "");
    assert.equal(timeAgo(null, NOW), "");
  });

  test("status and kind have labels; an unknown one is shown as it is", () => {
    assert.deepEqual(statusBadge("new"), { label: "New", tone: "new" });
    assert.equal(statusBadge("hidden").tone, "warn");
    assert.deepEqual(statusBadge("odd"), { label: "odd", tone: "neutral" });
    assert.deepEqual([kindLabel("comment"), kindLabel("mention"), kindLabel("x")], ["Comment", "Mention", "x"]);
  });

  test("the nav badge shows nothing for zero and caps at 99+", () => {
    assert.deepEqual([0, undefined, null, -3, 1, 99, 100, 1234].map(newBadgeText), [
      "",
      "",
      "",
      "",
      "1",
      "99",
      "99+",
      "99+",
    ]);
  });
});

describe("replied badges", () => {
  test("none for an item that wasn't answered", () => {
    assert.equal(replyBadge(null), null);
    assert.equal(replyBadge(undefined), null);
    assert.equal(replyBadge({ rehearsal: false }), null);
  });

  test("a rehearsal says nothing was sent, a real reply says sent, each with its mode", () => {
    const rehearsal = replyBadge({ rehearsal: true, mode: "private", at: "2026-10-20T10:00:00Z" });
    assert.deepEqual([rehearsal.label, rehearsal.tone], ["Rehearsal (private)", "warn"]);
    assert.match(rehearsal.title, /nothing was sent/);
    const sent = replyBadge({ rehearsal: false, mode: "public", at: "2026-10-20T10:00:00Z" });
    assert.deepEqual([sent.label, sent.tone], ["Sent (public)", "good"]);
    assert.equal(replyBadge({ rehearsal: false, mode: "both", at: "2026-10-20T10:00:00Z" }).label, "Sent (both)");
    assert.match(replyBadge({ rehearsal: false, at: "x", by: "u1" }).title, /by a person/);
    assert.match(replyBadge({ rehearsal: false, at: "x", rule: "r1" }).title, /under a rule/);
  });

  test("replying again to a sent reply asks first; a rehearsal or no reply does not", () => {
    assert.match(replyAgainText({ reply: { rehearsal: false, at: "x" } }), /already answered/);
    assert.equal(replyAgainText({ reply: { rehearsal: true, at: "x" } }), null);
    assert.equal(replyAgainText({ reply: null }), null);
  });
});

describe("actions", () => {
  const item = (extra = {}) => ({ actions: ALL, status: "new", ...extra });
  const keys = (buttons) => buttons.map((b) => b.key);

  test("an admin gets every action the network offers, then Make a rule", () => {
    assert.deepEqual(keys(actionButtons(item(), ADMIN)), ["reply", "like", "hide", "delete", "message", "rule"]);
  });

  test("only what the network has: a network with no like or delete doesn't show them", () => {
    assert.deepEqual(keys(actionButtons(item({ actions: ["reply", "hide"] }), ADMIN)), ["reply", "hide", "rule"]);
    assert.deepEqual(keys(actionButtons(item({ actions: [] }), ADMIN)), ["rule"]);
  });

  test("only what the role may do: an editor can like and hide but not reply, delete or message", () => {
    assert.deepEqual(keys(actionButtons(item(), EDITOR)), ["like", "hide", "rule"]);
    assert.deepEqual(keys(actionButtons(item(), {})), []);
  });

  test("a hidden item offers Unhide; delete is destructive; reply and message take text", () => {
    const buttons = actionButtons(item({ status: "hidden" }), ADMIN);
    assert.equal(buttons.find((b) => b.key === "hide").label, "Unhide");
    assert.equal(buttons.find((b) => b.key === "delete").destructive, true);
    assert.deepEqual(
      buttons.filter((b) => b.needsText).map((b) => b.key),
      ["reply", "message"],
    );
    assert.equal(buttons.find((b) => b.key === "like").destructive, undefined);
  });

  test("Open on network links only to an http(s) address", () => {
    assert.equal(openHref({ url: "https://x.example/c/1" }), "https://x.example/c/1");
    assert.equal(openHref({ url: "http://x.example" }), "http://x.example");
    assert.equal(openHref({ url: "javascript:alert(1)" }), null);
    assert.equal(openHref({ url: "" }), null);
    assert.equal(openHref({ url: null }), null);
  });

  test("deleting asks first, naming the author and the network", () => {
    assert.match(
      confirmText("delete", { network: "instagram", author: { handle: "alice" } }),
      /Delete @alice's comment on instagram/,
    );
    assert.equal(confirmText("like", { network: "x", author: {} }), "");
  });
});

describe("the reply form", () => {
  test("private is the default whenever the network offers it, and the toggle shows only with both modes", () => {
    assert.deepEqual(replyForm(["private", "public"]), {
      modes: ["private", "public"],
      mode: "private",
      showToggle: true,
    });
    assert.deepEqual(replyForm(["public", "private"]), {
      modes: ["private", "public"],
      mode: "private",
      showToggle: true,
    });
    assert.deepEqual(replyForm(["private"]), { modes: ["private"], mode: "private", showToggle: false });
  });

  test("a network with public only defaults to public, with no toggle", () => {
    assert.deepEqual(replyForm(["public"]), { modes: ["public"], mode: "public", showToggle: false });
    assert.deepEqual(replyForm([]), { modes: [], mode: "private", showToggle: false });
  });

  test("the text is trimmed, and blank is nothing to send", () => {
    assert.equal(replyText("  hello \n"), "hello");
    assert.equal(replyText("   "), null);
    assert.equal(replyText(""), null);
  });
});

describe("filters", () => {
  test("they come from the page URL, dropping a kind or status it doesn't know", () => {
    const f = parseFilters(new URLSearchParams("integration=ig&kind=mention&status=new&q=%20price "));
    assert.deepEqual(f, { integration: "ig", kind: "mention", status: "new", q: "price" });
    assert.deepEqual(parseFilters(new URLSearchParams("kind=tweet&status=done")), NO_FILTERS);
    assert.deepEqual(parseFilters(new URLSearchParams("")), NO_FILTERS);
  });

  test("they go back into the page URL and the API query without the empty ones", () => {
    assert.equal(filtersToQuery(NO_FILTERS), "");
    assert.equal(
      filtersToQuery({ integration: "ig", kind: "", status: "new", q: "a b" }),
      "?integration=ig&status=new&q=a+b",
    );
    assert.equal(apiQuery(NO_FILTERS), "limit=50");
    assert.equal(
      apiQuery({ integration: "ig", kind: "comment", status: "seen", q: "price" }, 100),
      "integration=ig&kind=comment&status=seen&q=price&limit=50&offset=100",
    );
    assert.equal(apiQuery(NO_FILTERS, 0, 10), "limit=10");
  });

  test("hasFilters is true for any non-blank filter", () => {
    assert.equal(hasFilters(NO_FILTERS), false);
    assert.equal(hasFilters({ ...NO_FILTERS, q: "  " }), false);
    assert.equal(hasFilters({ ...NO_FILTERS, kind: "reply" }), true);
  });

  test("the integration options name the network unless the name already does", () => {
    assert.deepEqual(
      integrationOptions([
        { slug: "ig", name: "Instagram", network: "instagram" },
        { slug: "shop", name: "Shop account", network: "mastodon" },
      ]),
      [
        { value: "ig", label: "Instagram" },
        { value: "shop", label: "Shop account (mastodon)" },
      ],
    );
  });
});

describe("the empty state", () => {
  const summary = (show = true) => ({ show, new: 0, integrations: [], can: {} });

  test("filters say so first", () => {
    assert.equal(emptyNotice(summary(), true).title, "Nothing matches these filters");
  });

  test("no social integration: say so and link to Integrations", () => {
    const n = emptyNotice(summary(false), false);
    assert.equal(n.title, "No social network is connected");
    assert.equal(n.link.href, "/workspace/settings/integrations");
  });

  test("a connected network with nothing yet says when to expect items; there is nothing to set up", () => {
    const n = emptyNotice(summary(), false);
    assert.equal(n.title, "Nothing here yet");
    assert.equal(n.link, undefined);
    assert.match(n.body, /5 minutes/);
    assert.doesNotMatch(n.body, /set up|rehearsal/i);
  });

  test("a network whose plugin can't read comments says there is no inbox for it", () => {
    const n = emptyNotice(summary(), false, { name: "Poster", readsComments: false });
    assert.match(n.title, /Poster can't be read/);
  });

  test("no summary yet (it failed to load) still says something useful", () => {
    assert.equal(emptyNotice(null, false).title, "Nothing here yet");
  });
});

describe("errors", () => {
  test("the API's own sentence is shown; nothing falls back to a general line", () => {
    assert.equal(errorMessage(new Error("mastodon can't send a private reply")), "mastodon can't send a private reply");
    assert.equal(errorMessage(new Error("  ")), "Something went wrong.");
    assert.equal(errorMessage(undefined), "Something went wrong.");
    assert.equal(errorMessage("plain"), "plain");
  });
});
