// Approval cards (approvals.ts): grouping a flattened `pending` by who asked, the decisions a card sends,
// and the bubble's inline card. Run with `npm test` — plain `node --test`, which strips approvals.ts's
// types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { approvalCardHtml, argsPreview, decidedSummary, decisionsFrom, groupPending, viaText } from "./approvals.ts";

const esc = (s) =>
  String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

const own = { id: "c2", tool: "mcp__srv__send", arguments: { to: "a@b" } };
const workshop = (id, tool = "run_workflow") => ({
  id: `c1/${id}`,
  tool,
  arguments: { name: "nightly" },
  via: "workshop",
  viaName: "Workshop",
  viaChain: ["workshop"],
  childThreadId: "t-w",
});
const materials = {
  id: "c3/c8/c9",
  tool: "attach_tag",
  arguments: {},
  via: "materials",
  viaName: "Materials",
  viaChain: ["workshop", "materials"],
  childThreadId: "t-m",
};

describe("groupPending", () => {
  test("test_group_pending_puts_own_asks_first_then_each_specialist", () => {
    const groups = groupPending([workshop("c7"), own, materials, workshop("c8", "mcp__x")]);
    assert.deepEqual(
      groups.map((g) => [g.via, g.calls.map((c) => c.id)]),
      [
        [null, ["c2"]],
        ["workshop", ["c1/c7", "c1/c8"]],
        ["materials", ["c3/c8/c9"]],
      ],
    );
  });

  test("test_group_pending_without_own_asks_has_no_empty_group", () => {
    assert.deepEqual(
      groupPending([workshop("c7")]).map((g) => g.via),
      ["workshop"],
    );
    assert.deepEqual(groupPending(null), []);
  });

  test("test_via_text_names_the_chain_when_hand_offs_nest", () => {
    const [, nested] = groupPending([workshop("c7"), materials]);
    assert.equal(
      viaText(nested, (s) => s[0].toUpperCase() + s.slice(1)),
      "via Workshop → Materials",
    );
    assert.equal(viaText(groupPending([workshop("c7")])[0]), "via Workshop");
    assert.equal(viaText(groupPending([own])[0]), "");
  });
});

describe("decisions", () => {
  test("test_decisions_from_sends_every_id_checked_approves", () => {
    const choices = [
      { id: "c2", checked: true },
      { id: "c1/c7", checked: false },
    ];
    assert.deepEqual(decisionsFrom(choices), { c2: "approve", "c1/c7": "deny" });
  });

  test("test_deny_all_denies_even_checked_calls", () => {
    assert.deepEqual(decisionsFrom([{ id: "c2", checked: true }], true), { c2: "deny" });
  });

  test("test_decided_summary_lists_approved_then_denied_tools", () => {
    assert.equal(
      decidedSummary([own, workshop("c7")], { "c1/c7": "approve" }),
      "Approved run_workflow · denied mcp__srv__send",
    );
    assert.equal(decidedSummary([own], { c2: "deny" }), "Denied mcp__srv__send");
  });

  test("test_args_preview_is_one_short_line", () => {
    assert.equal(argsPreview({ q: "x", n: 2 }), "q: x, n: 2");
    assert.equal(argsPreview({ q: "y".repeat(100) }, 10), "q: yyyyyy…");
    assert.equal(argsPreview(null), "");
  });
});

describe("approvalCardHtml (bubble)", () => {
  const card = (over = {}) => ({
    cardId: "card-1",
    threadId: "t-root",
    agent: "marvin",
    pending: [own, workshop("c7")],
    askHref: "/workspace/settings/ai-ask?thread=t-root",
    ...over,
  });

  test("test_bubble_card_has_a_checkbox_per_call_and_a_via_chip", () => {
    const html = approvalCardHtml(card(), esc);
    assert.match(html, /data-card-id="card-1"/);
    assert.match(html, /data-call-id="c2" checked/);
    assert.match(html, /data-call-id="c1\/c7" checked/);
    assert.match(html, /<span class="mv-chip">via Workshop<\/span>/);
    assert.ok(html.indexOf("mcp__srv__send") < html.indexOf("via Workshop"), "own asks come first");
    assert.match(html, /data-mv-approve/);
    assert.match(html, /data-mv-deny/);
  });

  test("test_bubble_card_links_the_ask_page_only_while_it_is_on", () => {
    assert.match(approvalCardHtml(card(), esc), /Open on Ask page/);
    assert.doesNotMatch(approvalCardHtml(card({ askHref: null }), esc), /Open on Ask page/);
  });

  test("test_a_decided_card_is_disabled_and_says_what_was_decided", () => {
    const html = approvalCardHtml(card({ decided: { c2: "deny", "c1/c7": "approve" } }), esc);
    assert.match(html, /mv-approval resolved/);
    assert.doesNotMatch(html, /data-mv-approve/);
    assert.match(html, /data-call-id="c2" disabled/);
    assert.match(html, /data-call-id="c1\/c7" checked disabled/);
    assert.match(html, /Approved run_workflow · denied mcp__srv__send/);
  });

  test("test_a_superseded_card_says_a_newer_message_replaced_it", () => {
    const html = approvalCardHtml(card({ decided: "superseded" }), esc);
    assert.match(html, /newer message/);
    assert.doesNotMatch(html, / checked/);
  });

  test("test_bubble_card_escapes_tool_arguments", () => {
    const html = approvalCardHtml(card({ pending: [{ id: "c1", tool: "x", arguments: { q: "<script>" } }] }), esc);
    assert.doesNotMatch(html, /<script>/);
  });
});
