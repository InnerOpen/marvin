// What each upload surface offers, by the accept it is drawn with (lib/assetAccept.ts uploadChoices). One rule everywhere: the
// surfaces differ only in their accept, so these pin the accepts each one uses. Run with `npm test`.

import assert from "node:assert/strict";
import { test } from "node:test";

import { uploadChoices } from "./assetAccept.ts";
import { galleryAccept } from "./wizard.ts";

const offers = (accept, multiple = false) => {
  const c = uploadChoices(accept, multiple);
  return [c.upload, ...c.record];
};

test("test_assets_upload_page_offers_everything", () => {
  // assets/new.astro draws uploadChoices(null, true).
  assert.deepEqual(offers(null, true), ["Upload files", "audio", "video"]);
});

test("test_entry_field_offers_by_its_accept", () => {
  // LinkedItemsField draws uploadChoices(field.accept, multiple).
  assert.deepEqual(offers("audio/*"), ["Upload an audio file", "audio"]);
  assert.deepEqual(offers("video/*"), ["Upload a video", "video"]);
  assert.deepEqual(offers("image/*"), ["Upload an image"]);
  assert.deepEqual(offers("audio/*,video/*"), ["Upload a file", "audio", "video"]);
  assert.deepEqual(offers("application/pdf"), ["Upload a file"]);
  assert.deepEqual(offers(""), ["Upload any file", "audio", "video"]);
  assert.deepEqual(offers("image/*", true), ["Upload images"]);
});

test("test_guided_card_action_box_defaults_to_sound_only", () => {
  // setups/[slug].astro: a card action's file box takes `audio/*` unless it says (a take, a voice): never the camera.
  assert.deepEqual(offers("audio/*"), ["Upload an audio file", "audio"]);
});

test("test_guided_gallery_upload_and_add_file_follow_the_field", () => {
  const fields = [
    { key: "general_view", accept: null },
    { key: "take", accept: "audio/*" },
    { key: "clip", accept: "video/*" },
  ];
  // A gallery's upload with no accept of its own and an untyped field takes pictures (galleryAccept's default).
  assert.deepEqual(offers(galleryAccept({ upload: { field: "general_view" } }, fields)), ["Upload an image"]);
  assert.deepEqual(offers(galleryAccept({ upload: { field: "take" } }, fields)), ["Upload an audio file", "audio"]);
  assert.deepEqual(offers(galleryAccept({ upload: { field: "clip" } }, fields)), ["Upload a video", "video"]);
});

test("test_guided_choose_create_upload_defaults_to_pictures", () => {
  // WizardCreate: `create.upload.accept` or image/*.
  assert.deepEqual(offers("image/*"), ["Upload an image"]);
});

test("test_guided_upload_step_by_its_extensions", () => {
  // An upload step's accept is a list of extensions, joined.
  assert.deepEqual(offers([".fountain", ".txt"].join(",")), ["Upload a file"]);
  assert.deepEqual(offers([".mp3", ".wav", ".webm"].join(",")), ["Upload an audio file", "audio"]);
  assert.deepEqual(offers([".mp4", ".webm"].join(",")), ["Upload a video", "video"]);
  assert.deepEqual(offers(""), ["Upload any file", "audio", "video"]);
});
