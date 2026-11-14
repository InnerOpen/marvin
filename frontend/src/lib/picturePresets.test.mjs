// Picture presets on the entry type page (picturePresets.ts): the form <-> preset mapping, the steps in words, the sliders and
// the checks. Run with `npm test` (plain `node --test`). Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  blankForm,
  factorToSlider,
  formFits,
  formFromPreset,
  parseSteps,
  presetFromForm,
  previewLook,
  putPreset,
  sliderLabel,
  sliderToFactor,
  stepsFromForm,
  stepsWords,
  validateForm,
} from "./picturePresets.ts";

const ORNAMENT = {
  slug: "ornament-look",
  name: "Ornament look",
  description: "Square, bright, small",
  steps: [
    { op: "crop", aspect: "1:1", focus: "0.25,0.5" },
    { op: "resize", width: 800 },
    { op: "grade", brightness: 1.2, vignette: 0.18 },
    { op: "convert", format: "webp", quality: 80 },
  ],
};

describe("sliders", () => {
  test("percent maps to the factor the server takes, 0% leaving the picture as it is", () => {
    assert.equal(sliderToFactor("brightness", 0), 1);
    assert.equal(sliderToFactor("contrast", 10), 1.1);
    assert.equal(sliderToFactor("saturation", -50), 0.5);
    assert.equal(sliderToFactor("saturation", 100), 2);
    assert.equal(sliderToFactor("warmth", 15), 1.15);
    assert.equal(sliderToFactor("vignette", 18), 0.18);
  });

  test("a factor snaps to whole percent and stops at the slider's ends, as a range input does", () => {
    assert.equal(factorToSlider("brightness", 1.15), 15);
    assert.equal(factorToSlider("warmth", 0.92), -8);
    assert.equal(factorToSlider("brightness", 2.5), 100);
    assert.equal(factorToSlider("contrast", 0), -50);
    assert.equal(factorToSlider("vignette", 0.18), 18);
  });

  test("labels say plus or minus", () => {
    assert.equal(sliderLabel("brightness", 10), "+10%");
    assert.equal(sliderLabel("warmth", -5), "-5%");
    assert.equal(sliderLabel("contrast", 0), "0%");
    assert.equal(sliderLabel("vignette", 18), "18%");
  });
});

describe("form <-> preset", () => {
  test("a stored preset round-trips through the form", () => {
    const form = formFromPreset(ORNAMENT);
    assert.equal(form.crop, true);
    assert.equal(form.focus, "point");
    assert.deepEqual([form.focusX, form.focusY], [0.25, 0.5]);
    assert.equal(form.brightness, 20);
    assert.equal(form.contrast, 0);
    assert.equal(form.format, "webp");
    assert.deepEqual(presetFromForm(form), ORNAMENT);
    assert.equal(formFits(ORNAMENT.steps), true);
  });

  test("only what is switched on is written, in the form's order, and a slider at 0 is left out", () => {
    const form = { ...blankForm(), slug: "s", name: "S", grade: true, contrast: 10, saturation: 0, resize: true, height: "600", fit: "inside" };
    assert.deepEqual(stepsFromForm(form), [{ op: "resize", height: 600 }, { op: "grade", contrast: 1.1 }]);
    form.grade = false;
    form.format = "jpeg";
    assert.deepEqual(stepsFromForm(form), [{ op: "resize", height: 600 }, { op: "convert", format: "jpeg" }]);
  });

  test("crop focus: center is left out, subject and a point are written; another shape goes in the free box", () => {
    const form = { ...blankForm(), crop: true, aspect: "other", aspectOther: " 5:7 " };
    assert.deepEqual(stepsFromForm(form), [{ op: "crop", aspect: "5:7" }]);
    assert.deepEqual(stepsFromForm({ ...form, focus: "subject" }), [{ op: "crop", aspect: "5:7", focus: "subject" }]);
    const stored = formFromPreset({ slug: "a", name: "A", steps: [{ op: "crop", aspect: "7:5" }] });
    assert.equal(stored.aspect, "other");
    assert.equal(stored.aspectOther, "7:5");
  });

  test("a step that treats a picture the same way is kept as stored (its treated pictures are reused)", () => {
    const stored = {
      slug: "a",
      name: "A",
      steps: [{ op: "crop", aspect: "4x5", focus: "center" }, { op: "resize", width: 800, fit: "inside" }, { op: "grade", brightness: 1, contrast: 1.1 }],
    };
    const form = formFromPreset(stored);
    assert.equal(form.aspect, "4:5");
    assert.equal(formFits(stored.steps), true);
    assert.deepEqual(stepsFromForm(form, stored), stored.steps);
    form.width = "900";
    assert.deepEqual(stepsFromForm(form, stored)[1], { op: "resize", width: 900 });
  });

  test("blanks are null; a new preset starts with nothing switched on", () => {
    const form = blankForm();
    assert.equal(form.crop || form.resize || form.grade || !!form.format, false);
    assert.equal(presetFromForm({ ...form, slug: " x ", name: " X ", description: " " }).description, null);
  });
});

describe("formFits", () => {
  test("steps out of the form's order, or a treatment twice, don't fit", () => {
    assert.equal(formFits([{ op: "grade", preset: "warm" }, { op: "crop", aspect: "1:1" }]), false);
    assert.equal(formFits([{ op: "crop", aspect: "1:1" }, { op: "crop", aspect: "4:5" }]), false);
  });

  test("values a slider can't hold don't fit (off its grid or past its end)", () => {
    assert.equal(formFits([{ op: "grade", brightness: 1.125 }]), false);
    assert.equal(formFits([{ op: "grade", brightness: 2.5 }]), false);
    assert.equal(formFits([{ op: "crop", aspect: "1:1", focus: "0.333,0.5" }]), false);
  });

  test("a format on a crop, a stray key, or a neutral setting over a named grade don't fit", () => {
    assert.equal(formFits([{ op: "crop", aspect: "1:1", format: "webp" }]), false);
    assert.equal(formFits([{ op: "resize", width: 10, colors: 3 }]), false);
    assert.equal(formFits([{ op: "grade", preset: "rustic-warm", brightness: 1 }]), false);
    assert.equal(formFits([{ op: "grade", preset: "rustic-warm", brightness: 1.05 }]), true);
  });

  test("a workspace's named grade fits (the select keeps it)", () => {
    assert.equal(formFits([{ op: "grade", preset: "studio-blue" }]), true);
    assert.equal(formFromPreset({ slug: "a", name: "A", steps: [{ op: "grade", preset: "studio-blue" }] }).gradePreset, "studio-blue");
  });
});

test("the steps in words, as the server names them", () => {
  assert.equal(stepsWords(ORNAMENT.steps), "crop 1:1 at 0.25,0.5, resize 800×auto, grade brightness 1.2 vignette 0.18, webp");
  assert.equal(
    stepsWords([{ op: "crop", aspect: "4:5", focus: "subject" }, { op: "grade", preset: "warm", contrast: 1.1, format: "png" }, { op: "resize", height: 600 }]),
    "crop 4:5 subject, grade warm contrast 1.1 png, resize auto×600",
  );
});

describe("validateForm", () => {
  const named = () => ({ ...blankForm(), slug: "a", name: "A" });

  test("needs a name, a slug and at least one treatment", () => {
    assert.equal(validateForm({ ...blankForm(), slug: "Bad slug" }).length, 3);
    assert.deepEqual(validateForm({ ...named(), format: "webp" }), []);
  });

  test("checks the crop's shape and point", () => {
    assert.deepEqual(validateForm({ ...named(), crop: true, aspect: "1:1" }), []);
    assert.deepEqual(validateForm({ ...named(), crop: true, aspect: "other", aspectOther: "4x5" }), []);
    assert.equal(validateForm({ ...named(), crop: true, aspect: "other", aspectOther: "square" }).length, 1);
    assert.equal(validateForm({ ...named(), crop: true, focus: "point", focusX: 1.2 }).length, 1);
  });

  test("checks the size, fill needing both sides, a grade that does something, and the quality", () => {
    assert.equal(validateForm({ ...named(), resize: true }).length, 1);
    assert.equal(validateForm({ ...named(), resize: true, width: "800.5" }).length, 1);
    assert.equal(validateForm({ ...named(), resize: true, width: "800", fit: "cover" }).length, 1);
    assert.deepEqual(validateForm({ ...named(), resize: true, width: "800", height: "600", fit: "cover" }), []);
    assert.equal(validateForm({ ...named(), grade: true }).length, 1);
    assert.deepEqual(validateForm({ ...named(), grade: true, gradePreset: "muted" }), []);
    assert.equal(validateForm({ ...named(), format: "jpeg", quality: "101" }).length, 1);
  });
});

test("parseSteps reads a list of steps, or says what is wrong", () => {
  assert.deepEqual(parseSteps('[{"op":"crop","aspect":"1:1"}]'), { steps: [{ op: "crop", aspect: "1:1" }] });
  assert.ok("error" in parseSteps("[{"));
  assert.ok("error" in parseSteps("[]"));
  assert.ok("error" in parseSteps('[{"op":"blur"}]'));
  assert.ok("error" in parseSteps(JSON.stringify(Array.from({ length: 13 }, () => ({ op: "convert", format: "png" })))));
});

test("putPreset replaces by slug or adds at the end", () => {
  const list = [{ slug: "a", name: "A", steps: [] }, { slug: "b", name: "B", steps: [] }];
  assert.deepEqual(putPreset(list, { slug: "a2", name: "A2", steps: [] }, "a").map((p) => p.slug), ["a2", "b"]);
  assert.deepEqual(putPreset(list, { slug: "c", name: "C", steps: [] }, null).map((p) => p.slug), ["a", "b", "c"]);
});

test("previewLook turns the steps into CSS: the crop's shape and point, filters, a tint and a vignette", () => {
  const look = previewLook(ORNAMENT.steps);
  assert.equal(look.aspectRatio, "1 / 1");
  assert.equal(look.objectPosition, "25% 50%");
  assert.equal(look.filter, "brightness(1.2)");
  assert.equal(look.tint, null);
  assert.equal(look.vignette, 0.18);
  const warm = previewLook([{ op: "grade", preset: "rustic-warm" }]);
  assert.equal(warm.filter, "brightness(0.98) contrast(1.12) saturate(0.92)");
  assert.equal(warm.tint.color, "rgb(255 140 40)");
  assert.equal(previewLook([]).filter, "none");
});
