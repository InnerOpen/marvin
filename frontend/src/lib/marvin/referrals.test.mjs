// The bubble's "Continue with <agent> →" referral buttons (referrals.ts).

import assert from "node:assert/strict";
import { test } from "node:test";

import { referralQuestion, referralsHtml } from "./referrals.ts";

test("a referral becomes a button carrying the agent and the request, escaped", () => {
  const html = referralsHtml([{ agent: "marvin", name: "Elvira", question: 'Attach "denim" to <Built to Wear>', reason: "she can write" }]);
  assert.match(html, /data-mv-continue-agent="marvin"/);
  assert.match(html, /data-mv-question="Attach &quot;denim&quot; to &lt;Built to Wear&gt;"/);
  assert.match(html, /Continue with Elvira →/);
  assert.match(html, /she can write/);
});

test("nothing to continue with, nothing shown", () => {
  assert.equal(referralsHtml(undefined), "");
  assert.equal(referralsHtml([{ agent: "marvin", question: "  " }, { agent: "", question: "x" }]), "");
});

test("what the referring agent found travels in the sent question, as plain text", () => {
  const ids = ["0b0c1d2e-3f40-4152-8364-758697a8b9c0", "11111111-2222-4333-8444-555555555555"];
  const r = { agent: "marvin", name: "Marvin", question: "Attach these to the latest bench note", tool: "attach_asset", context: { entry: "bench-note-14", assetIds: ids, summary: "two denim shots" } };
  const q = referralQuestion(r);
  assert.ok(q.startsWith(`Attach these to the latest bench note\n\nHanded over with: entry bench-note-14; assets ${ids.join(", ")}`));
  assert.match(q, /note: two denim shots\. To do: attach_asset\. Check each before acting\.$/);
  assert.match(referralsHtml([r]), /Handed over with: entry bench-note-14/); // the button sends the same text
  assert.equal(referralQuestion({ agent: "m", question: " just this ", context: {} }), "just this");
  assert.match(referralQuestion({ agent: "m", question: "q", context: { assetIds: [ids[0]] } }), /asset 0b0c1d2e/);
});
