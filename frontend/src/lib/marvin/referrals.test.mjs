// The bubble's "Continue with <agent> →" referral buttons (referrals.ts).

import assert from "node:assert/strict";
import { test } from "node:test";

import { referralsHtml } from "./referrals.ts";

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
