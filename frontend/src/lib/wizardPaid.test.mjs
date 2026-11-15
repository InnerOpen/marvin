import assert from "node:assert/strict";
import { test } from "node:test";
import { namedList, paidCardsLine, paidConfirm, paidFields, paidLine, paidOf, paidSent, paidWarning } from "./wizardPaid.ts";

const fields = [
  { key: "spoken", label: "Words (what is said)" },
  { key: "direction", label: "Direction" },
  { key: "voice", label: "Voice" },
];

test("paid is true or an object: anything else is not paid", () => {
  assert.deepEqual(paidOf(true), { service: "", cost: "", sends: [], needs: [] });
  assert.equal(paidOf(false), null);
  assert.equal(paidOf(undefined), null);
  assert.equal(paidOf("yes"), null);
  assert.equal(paidOf(["spoken"]), null);
  assert.deepEqual(paidOf({ service: " ElevenLabs ", cost: "About 2 cents a line.", entry: "role", sends: ["spoken", "direction"], needs: ["direction", "voice"] }), {
    service: "ElevenLabs",
    cost: "About 2 cents a line.",
    entry: "role",
    sends: ["spoken", "direction"],
    needs: ["direction"], // only what is sent can be needed
  });
});

test("the notice says it is paid, to whom, and what it costs when the package says", () => {
  assert.equal(paidLine(paidOf(true)), "This sends your request to a paid outside service.");
  assert.equal(paidLine(paidOf({ service: "ElevenLabs", cost: "About 2 cents a line." })), "This sends your request to a paid outside service (ElevenLabs). About 2 cents a line.");
  assert.equal(paidLine(paidOf({ service: "ElevenLabs" }), "the Words and Direction above"), "This sends the Words and Direction above to a paid outside service (ElevenLabs).");
});

test("what will be sent is the text of the named fields as it is, under their labels; a needed one that is empty is missing", () => {
  const paid = paidOf({ sends: ["spoken", "direction", "voice"], needs: ["direction", "voice"] });
  assert.deepEqual(paidSent(paid, { spoken: " People say I am made of tin. ", direction: "", voice: "v1" }, fields), {
    lines: [
      { key: "spoken", label: "Words", value: "People say I am made of tin." },
      { key: "voice", label: "Voice", value: "v1" },
    ],
    missing: ["Direction"],
  });
  assert.deepEqual(paidSent(paid, null, []), { lines: [], missing: ["direction", "voice"] }); // nothing chosen: the keys stand in for labels
  assert.deepEqual(paidSent(paidOf(true), { spoken: "x" }, fields), { lines: [], missing: [] });
});

test("a missing direction is a warning, said once for one or several", () => {
  assert.equal(paidWarning([]), null);
  assert.equal(paidWarning(["Direction"]), "“Direction” is empty: it is sent without it.");
  assert.equal(paidWarning(["Direction", "Voice"]), "“Direction” and “Voice” are empty: it is sent without them.");
});

test("an add form's paid button names the fields it sends", () => {
  assert.equal(paidFields(paidOf({ sends: ["spoken", "direction", "voice"] }), fields), "Words, Direction and Voice");
  assert.equal(namedList(["Words"]), "Words");
  assert.equal(namedList([]), "");
});

test("a paid card button asks first, with the text that goes and what is missing", () => {
  const paid = paidOf({ service: "ElevenLabs", sends: ["spoken", "direction"], needs: ["direction"] });
  assert.equal(
    paidConfirm("Make this one", paid, paidSent(paid, { spoken: "A door creaks." }, fields)),
    "This sends your request to a paid outside service (ElevenLabs).\n\nWords: A door creaks.\n\n“Direction” is empty: it is sent without it.\n\nMake this one?",
  );
  assert.equal(paidConfirm("Make this one", paidOf(true), paidSent(paidOf(true), {}, fields)), "This sends your request to a paid outside service.\n\nMake this one?");
  const long = paidConfirm("Go", paid, paidSent(paid, { spoken: "x".repeat(900), direction: "soft" }, fields));
  assert.ok(long.includes(`${"x".repeat(399)}…`) && !long.includes("x".repeat(400)));
});

test("a gallery says once which of its card buttons are paid", () => {
  const el = paidOf({ service: "ElevenLabs" });
  assert.equal(paidCardsLine([{ label: "Make this one", paid: el }]), "“Make this one” sends to a paid outside service (ElevenLabs), and asks first.");
  assert.equal(
    paidCardsLine([{ label: "Make this one", paid: el }, { label: "Make it again", paid: el }, { label: "Draw it", paid: paidOf(true) }]),
    "“Make this one”, “Make it again” and “Draw it” send to a paid outside service (ElevenLabs), and each asks first.",
  );
});
