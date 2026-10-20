// Which entry types are offered for writing (entryTypeListing.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  internalReason,
  isListedType,
  listedTypes,
  submissionDestination,
  submissionKind,
  usedBy,
} from "./entryTypeListing.ts";

describe("internal entry types", () => {
  test("a type is internal only when the flag says listed is false", () => {
    assert.equal(isListedType({ slug: "note" }), true);
    assert.equal(isListedType({ slug: "note", capabilitiesJson: {} }), true);
    assert.equal(isListedType({ slug: "note", capabilitiesJson: { listed: true } }), true);
    assert.equal(isListedType({ slug: "note", capabilitiesJson: { publishable: false } }), true);
    assert.equal(isListedType({ slug: "secret", capabilitiesJson: { listed: false } }), false);
    assert.equal(isListedType(null), true);
    assert.equal(isListedType(undefined), true);
  });

  test("a slug alone no longer makes a type internal: the migration sets the flag on the Social types", () => {
    for (const slug of ["social-auto-reply", "social-reply-log"]) {
      assert.equal(isListedType({ slug, capabilitiesJson: null }), true);
      assert.equal(isListedType({ slug, capabilitiesJson: { listed: false } }), false);
    }
  });

  test("a form is not internal because of where its submissions go: the flag decides", () => {
    const form = (submission, listed) => ({
      slug: "contact",
      capabilitiesJson: { submittable: true, ...(submission ? { submission } : {}), ...(listed === undefined ? {} : { listed }) },
    });
    assert.equal(isListedType(form(null)), true); // the destination defaults to audience; listed is its own switch
    assert.equal(isListedType(form({ destination: "audience" })), true);
    assert.equal(isListedType(form({ destination: "audience" }, false)), false);
    assert.equal(isListedType(form({ destination: "entries" })), true);
    assert.equal(isListedType(form({ destination: "audience" }, true)), true); // an Audience form switched to listed
  });

  test("the types to offer leave the unlisted ones out and keep the order", () => {
    const types = [
      { slug: "page" },
      { slug: "social-auto-reply", capabilitiesJson: { listed: false } },
      { slug: "post", capabilitiesJson: { listed: false } },
      { slug: "note" },
      { slug: "contact", capabilitiesJson: { submittable: true, submission: { destination: "audience" }, listed: true } },
    ];
    assert.deepEqual(
      listedTypes(types).map((t) => t.slug),
      ["page", "note", "contact"],
    );
    assert.deepEqual(listedTypes(null), []);
  });

  test("the destination and kind default to audience and message, and are null off a form", () => {
    const form = (submission) => ({ capabilitiesJson: { submittable: true, submission } });
    assert.equal(submissionDestination(form(undefined)), "audience");
    assert.equal(submissionDestination(form({ destination: "entries" })), "entries");
    assert.equal(submissionDestination(form({ destination: "bogus" })), "audience");
    assert.equal(submissionKind(form(undefined)), "message");
    assert.equal(submissionKind(form({ kind: "signup" })), "signup");
    assert.equal(submissionDestination({ capabilitiesJson: {} }), null);
    assert.equal(submissionKind(null), null);
  });

  test("what uses a type (a hint) and the Internal badge's reason", () => {
    const unlisted = (extra) => ({ capabilitiesJson: { listed: false, ...extra.caps }, slug: extra.slug });
    assert.equal(usedBy({ slug: "social-auto-reply" }), "Audience › Social › Rules");
    assert.equal(usedBy({ slug: "contact", capabilitiesJson: { submittable: true } }), "Audience › Submissions");
    assert.equal(usedBy({ slug: "n", capabilitiesJson: { submittable: true, submission: { kind: "signup" } } }), "Audience › Subscribers");
    assert.equal(usedBy({ slug: "t", capabilitiesJson: { submittable: true, submission: { destination: "entries" } } }), null);
    assert.equal(usedBy({ slug: "l", capabilitiesJson: { submittable: true, submission: { destination: "entries", kind: "signup" } } }), "Audience › Subscribers");
    assert.equal(usedBy({ slug: "note" }), null);
    assert.equal(internalReason({ slug: "note" }), null); // listed: no badge
    assert.match(internalReason(unlisted({ slug: "social-auto-reply", caps: {} })), /kept out of All entries.*Used by Audience › Social › Rules\./);
    assert.match(internalReason(unlisted({ slug: "contact", caps: { submittable: true } })), /Used by Audience › Submissions\./);
    assert.doesNotMatch(internalReason(unlisted({ slug: "other", caps: {} })), /Used by/);
  });
});
