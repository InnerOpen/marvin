// Which entry types are offered for writing (entryTypeListing.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  hasAssetField,
  internalReason,
  isListedType,
  isOfferedInNew,
  listedTypes,
  lockReason,
  newMenuTypes,
  onlyAssetType,
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

describe("onlyAssetType", () => {
  const typed = (slug, ...fieldTypes) => ({ slug, schemaJson: { fields: fieldTypes.map((type) => ({ type })) } });

  test("an image field or an image list counts as an asset field", () => {
    assert.equal(hasAssetField(typed("a", "text", "asset")), true);
    assert.equal(hasAssetField(typed("b", "asset-list")), true);
    assert.equal(hasAssetField(typed("c", "text", "resource")), false);
    assert.equal(hasAssetField({ slug: "d" }), false);
  });

  test("the one listed type with an asset field is the answer", () => {
    const artwork = typed("artwork", "text", "asset");
    assert.equal(onlyAssetType([typed("note", "text"), artwork]), artwork);
  });

  test("several types with an asset field leave the choice to the person", () => {
    assert.equal(onlyAssetType([typed("artwork", "asset"), typed("post", "asset-list")]), null);
  });

  test("no type with an asset field gives null", () => {
    assert.equal(onlyAssetType([typed("note", "text")]), null);
    assert.equal(onlyAssetType([]), null);
    assert.equal(onlyAssetType(null), null);
  });

  test("an internal type with an asset field is not offered, so it doesn't make the answer ambiguous", () => {
    const artwork = typed("artwork", "asset");
    const hidden = { ...typed("social-reply-log", "asset"), capabilitiesJson: { listed: false } };
    assert.equal(onlyAssetType([artwork, hidden]), artwork);
    assert.equal(onlyAssetType([hidden]), null);
  });
});

describe("lockReason", () => {
  test("a locked type gives its reason, anything else gives null", () => {
    assert.equal(lockReason({ slug: "playbook", lockedReason: "Playbooks are built on this type." }), "Playbooks are built on this type.");
    assert.equal(lockReason({ slug: "note", lockedReason: null }), null);
    assert.equal(lockReason({ slug: "note", lockedReason: "" }), null);
    assert.equal(lockReason({ slug: "note" }), null);
    assert.equal(lockReason(null), null);
  });
});

describe("the New menu", () => {
  const t = (name, sortOrder = 0, caps = undefined) => ({ name, sortOrder, capabilitiesJson: caps });

  test("a listed type is offered unless offer_in_new is false; an internal one never is", () => {
    assert.equal(isOfferedInNew(t("Note")), true);
    assert.equal(isOfferedInNew(t("Note", 0, {})), true);
    assert.equal(isOfferedInNew(t("Note", 0, { offer_in_new: true })), true);
    assert.equal(isOfferedInNew(t("Take", 0, { offer_in_new: false })), false);
    assert.equal(isOfferedInNew(t("Take", 0, { offerInNew: false })), false);
    assert.equal(isOfferedInNew(t("Take", 0, { offer_in_new: true, offerInNew: false })), true); // the stored spelling wins
    assert.equal(isOfferedInNew(t("Rule", 0, { listed: false })), false);
    assert.equal(isOfferedInNew(t("Rule", 0, { listed: false, offer_in_new: true })), false);
  });

  test("the offered types come by sort order, then name, and the input is left as it was", () => {
    const types = [t("Story", 2), t("Beat", 1), t("Take", 0, { offer_in_new: false }), t("Actor", 1), t("Rule", 0, { listed: false }), t("Zed")];
    const { shown, more } = newMenuTypes(types, 12);
    assert.deepEqual(shown.map((x) => x.name), ["Zed", "Actor", "Beat", "Story"]);
    assert.equal(more, false);
    assert.deepEqual(types.map((x) => x.name), ["Story", "Beat", "Take", "Actor", "Rule", "Zed"]);
  });

  test("past the cap the first ones are shown and more is set; at the cap it is not", () => {
    const many = (n) => Array.from({ length: n }, (_, i) => t(`Type ${String(i).padStart(2, "0")}`, i));
    const thirteen = newMenuTypes(many(13), 12);
    assert.equal(thirteen.shown.length, 12);
    assert.equal(thirteen.shown[0].name, "Type 00");
    assert.equal(thirteen.more, true);
    assert.deepEqual(newMenuTypes(many(12), 12).more, false);
    assert.equal(newMenuTypes(many(13), 6).shown.length, 6);
  });

  test("no types, or none to offer, is an empty menu", () => {
    assert.deepEqual(newMenuTypes(null, 12), { shown: [], more: false });
    assert.deepEqual(newMenuTypes([t("Take", 0, { offer_in_new: false })], 12), { shown: [], more: false });
  });
});
