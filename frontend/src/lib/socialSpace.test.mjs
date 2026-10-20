// Social as its own space (socialSpace.ts): the sidebar group, the network pages' tabs, the auto-reply switch, rules and
// replies. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  autoReplySwitch,
  findNetwork,
  isSocialPath,
  MODES,
  modeHelp,
  modeOf,
  networkPath,
  orderRules,
  parseReplyFilter,
  parseTab,
  publishAction,
  repliesEmpty,
  repliesQuery,
  replyBy,
  replyRow,
  ruleBadges,
  ruleReplyLine,
  ruleScope,
  rulesEmpty,
  ruleTitle,
  socialNav,
  tabLinks,
} from "./socialSpace.ts";

const net = (slug, extra = {}) => ({
  slug,
  name: slug.toUpperCase(),
  provider: "mastodon",
  network: "mastodon",
  autoReply: "off",
  new: 0,
  canReply: true,
  readsComments: true,
  ...extra,
});
const summary = (integrations, extra = {}) => ({
  show: integrations.length > 0,
  new: integrations.reduce((n, i) => n + i.new, 0),
  integrations,
  can: {},
  ...extra,
});
const ADMIN = { auto_reply: true, publish: true, rule: true, rules: true };
const EDITOR = { auto_reply: false, publish: true, rule: true, rules: true };
const VIEWER = {};

describe("routes and tabs", () => {
  test("a network's page is its slug under /workspace/social, the inbox being the page itself", () => {
    assert.equal(networkPath("ig"), "/workspace/social/ig");
    assert.equal(networkPath("ig", "inbox"), "/workspace/social/ig");
    assert.equal(networkPath("ig", "rules"), "/workspace/social/ig?tab=rules");
    assert.equal(networkPath("my shop/1", "replies"), "/workspace/social/my%20shop%2F1?tab=replies");
  });

  test("the tab comes from the query; anything unknown is the inbox", () => {
    assert.equal(parseTab(new URLSearchParams("tab=rules")), "rules");
    assert.equal(parseTab(new URLSearchParams("tab=replies")), "replies");
    assert.equal(parseTab(new URLSearchParams("tab=nope")), "inbox");
    assert.equal(parseTab(new URLSearchParams("")), "inbox");
  });

  test("the tabs are Inbox · Rules · Replies, the active one marked", () => {
    const tabs = tabLinks("ig", "rules");
    assert.deepEqual(
      tabs.map((t) => t.label),
      ["Inbox", "Rules", "Replies"],
    );
    assert.deepEqual(
      tabs.map((t) => t.current),
      [false, true, false],
    );
    assert.equal(tabs[0].href, "/workspace/social/ig");
  });

  test("a network is found by slug; Social's paths are recognised", () => {
    const s = summary([net("ig"), net("m")]);
    assert.equal(findNetwork(s, "m").slug, "m");
    assert.equal(findNetwork(s, "x"), null);
    assert.equal(findNetwork(null, "x"), null);
    assert.ok(isSocialPath("/workspace/social") && isSocialPath("/workspace/social/ig"));
    assert.ok(!isSocialPath("/workspace/socials") && !isSocialPath("/workspace/entries"));
  });
});

describe("the sidebar group", () => {
  test("hidden unless an enabled integration offers a social capability", () => {
    assert.equal(socialNav(null), null);
    assert.equal(socialNav(undefined), null);
    assert.equal(socialNav(summary([])), null);
    assert.equal(socialNav({ show: false, new: 5, integrations: [net("ig")], can: {} }), null);
  });

  test("the Inbox first with the new count, then one entry per connected network with its logo's provider and count", () => {
    const nav = socialNav(summary([net("ig", { provider: "instagram", new: 3 }), net("m", { new: 1 })]));
    assert.equal(nav.label, "Social");
    assert.equal(nav.badge, "4");
    assert.deepEqual(
      nav.children.map((c) => [c.label, c.href, c.provider, c.badge]),
      [
        ["Inbox", "/workspace/social", null, "4"],
        ["IG", "/workspace/social/ig", "instagram", "3"],
        ["M", "/workspace/social/m", "mastodon", "1"],
      ],
    );
    assert.equal(nav.children[1].badgeLabel, "3 new");
  });

  test("no badge for zero, 99+ past 99", () => {
    const quiet = socialNav(summary([net("ig")]));
    assert.equal(quiet.badge, "");
    assert.equal(quiet.children[1].badge, "");
    assert.equal(socialNav(summary([net("ig", { new: 250 })])).badge, "99+");
  });
});

describe("the auto-reply switch", () => {
  test("off, rehearsal, on — each with one line of explanation", () => {
    assert.deepEqual(
      MODES.map((m) => m.value),
      ["off", "rehearsal", "on"],
    );
    for (const m of MODES) assert.ok(m.help.length > 20 && !m.help.includes("\n"));
    assert.match(modeHelp("rehearsal"), /dry run/);
    assert.match(modeHelp("off"), /still read/);
    assert.match(modeHelp("unknown"), /Nothing is answered/);
  });

  test("a network with no mode, or an unknown one, is off", () => {
    assert.equal(modeOf({ autoReply: "on" }), "on");
    assert.equal(modeOf({ autoReply: "rehearsal" }), "rehearsal");
    assert.equal(modeOf({ autoReply: "banana" }), "off");
    assert.equal(modeOf(null), "off");
  });

  test("only an admin can change it", () => {
    const admin = autoReplySwitch(net("ig", { autoReply: "rehearsal" }), ADMIN);
    assert.deepEqual([admin.editable, admin.value, admin.note], [true, "rehearsal", null]);
    assert.match(admin.help, /dry run/);
    const editor = autoReplySwitch(net("ig"), EDITOR);
    assert.equal(editor.editable, false);
    assert.match(editor.note, /admin/);
    assert.equal(autoReplySwitch(net("ig"), VIEWER).editable, false);
  });

  test("a network that can't reply offers only off, and says why", () => {
    const quiet = autoReplySwitch(net("b", { canReply: false, name: "Bluesky" }), ADMIN);
    assert.deepEqual(
      quiet.options.map((o) => o.value),
      ["off"],
    );
    assert.equal(quiet.editable, false);
    assert.match(quiet.note, /Bluesky can't send replies/);
  });
});

const rule = (extra = {}) => ({
  id: "1",
  slug: "r",
  title: "r",
  status: "published",
  published: true,
  keywords: ["price"],
  reply: "Check the link",
  networks: [],
  allNetworks: true,
  post: "",
  replyAs: "private",
  alsoLike: false,
  kinds: ["comment"],
  legacy: false,
  path: "/workspace/entries/1",
  ...extra,
});

describe("rules", () => {
  test("listed in the order the engine reads them: one post, then this network, then every network, oldest first within each", () => {
    const rules = [
      rule({ id: "all-1" }),
      rule({ id: "net-1", allNetworks: false, networks: ["ig"] }),
      rule({ id: "post-all", post: "p9" }),
      rule({ id: "all-2" }),
      rule({ id: "post-net", post: "p9", allNetworks: false, networks: ["ig"] }),
      rule({ id: "net-2", allNetworks: false, networks: ["ig"] }),
    ];
    assert.deepEqual(
      orderRules(rules).map((r) => r.id),
      ["post-net", "post-all", "net-1", "net-2", "all-1", "all-2"],
    );
  });

  test("the scope says all networks, this network, or the networks it names, and one post", () => {
    assert.equal(ruleScope(rule(), "ig"), "All networks");
    assert.equal(ruleScope(rule({ allNetworks: false, networks: ["ig"] }), "ig"), "This network");
    assert.equal(ruleScope(rule({ allNetworks: false, networks: ["ig", "m"] }), "ig"), "This network");
    assert.equal(ruleScope(rule({ allNetworks: false, networks: ["m", "b"] }), "ig"), "m, b");
    assert.equal(ruleScope(rule({ post: "p1" }), null), "All networks · one post");
  });

  test("a published rule and a draft are told apart; an Instagram rule is marked", () => {
    assert.deepEqual(
      ruleBadges(rule()).map((b) => [b.label, b.tone]),
      [["Published", "good"]],
    );
    assert.deepEqual(
      ruleBadges(rule({ published: false })).map((b) => b.label),
      ["Draft"],
    );
    assert.deepEqual(
      ruleBadges(rule({ legacy: true })).map((b) => b.label),
      ["Published", "Instagram rule"],
    );
  });

  test("a row names the keywords and the reply, or nudges while they are blank", () => {
    assert.equal(ruleTitle(rule({ keywords: ["price", "cost"] })), "price, cost");
    assert.equal(ruleTitle(rule({ keywords: [] })), "No keywords yet");
    assert.equal(ruleReplyLine(rule({ reply: "  Check   the link " })), "Check the link");
    assert.equal(ruleReplyLine(rule({ reply: "" })), "No reply written yet");
    assert.ok(ruleReplyLine(rule({ reply: "word ".repeat(100) })).endsWith("…"));
  });

  test("publish or unpublish is offered to those who may publish, and says what it does", () => {
    assert.deepEqual(publishAction(rule({ published: false }), EDITOR), {
      label: "Publish",
      publish: true,
      note: "Publishing approves the reply text: it is sent as written.",
    });
    assert.equal(publishAction(rule(), EDITOR).label, "Unpublish");
    assert.equal(publishAction(rule(), EDITOR).publish, false);
    assert.equal(publishAction(rule(), VIEWER), null);
  });

  test("the empty state offers a new rule to those who can make one", () => {
    assert.match(rulesEmpty({ name: "Instagram" }, EDITOR).body, /Start one for Instagram/);
    assert.match(rulesEmpty({ name: "Instagram" }, VIEWER).body, /editor can start one/);
  });
});

describe("replies", () => {
  const item = (reply) => ({ author: { handle: "alice" }, reply });
  const at = "2026-10-20T10:00:00Z";

  test("none for an item without a reply", () => {
    assert.equal(replyRow(item(null)), null);
    assert.equal(replyRow(item({ rehearsal: false })), null);
  });

  test("a live reply says who, what, by which rule and when, and links the rule", () => {
    const row = replyRow(
      item({ rehearsal: false, mode: "private", text: "Check the link", rule: "price-rule", ruleEntryId: "e9", at }),
    );
    assert.deepEqual(
      [row.who, row.line, row.live, row.badge.label, row.by, row.at, row.ruleHref],
      ["@alice", "Check the link", true, "Live (private)", "by rule price-rule", at, "/workspace/entries/e9"],
    );
  });

  test("a rehearsal says nothing was sent", () => {
    const row = replyRow(item({ rehearsal: true, mode: "public", text: "x", rule: "r", at }));
    assert.deepEqual([row.live, row.badge.label, row.badge.tone], [false, "Rehearsal (public)", "warn"]);
    assert.match(row.badge.title, /nothing was sent/);
  });

  test("a person's reply names them, or says a person", () => {
    assert.equal(replyBy({ by: "u1", byName: "Jared" }), "by Jared");
    assert.equal(replyBy({ by: "u1" }), "by a person");
    assert.equal(replyBy({ rule: "r1" }), "by rule r1");
    assert.equal(replyBy({}), "by a rule");
    assert.equal(replyRow(item({ rehearsal: false, at, by: "u1", byName: "Jared", text: "hi" })).ruleHref, null);
  });

  test("a reply with no recorded text still has a line", () => {
    assert.equal(replyRow(item({ rehearsal: false, at })).line, "(no text recorded)");
  });

  test("the empty state says auto-reply is off when it is", () => {
    assert.match(repliesEmpty({ name: "Instagram", autoReply: "off" }).body, /Auto-reply is off for Instagram/);
    assert.match(repliesEmpty({ name: "Instagram", autoReply: "on" }).body, /show here with the rule/);
  });

  test("the filter becomes the API's rehearsal parameter, and comes back from the URL", () => {
    assert.equal(repliesQuery("ig", "all"), "integration=ig&limit=50");
    assert.equal(repliesQuery("ig", "live"), "integration=ig&limit=50&rehearsal=false");
    assert.equal(repliesQuery("ig", "rehearsal", 50), "integration=ig&limit=50&rehearsal=true&offset=50");
    assert.equal(parseReplyFilter(new URLSearchParams("show=live")), "live");
    assert.equal(parseReplyFilter(new URLSearchParams("show=rehearsal")), "rehearsal");
    assert.equal(parseReplyFilter(new URLSearchParams("show=x")), "all");
  });
});
