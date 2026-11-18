import test from "node:test";
import assert from "node:assert/strict";
import {
  acceptFamilies,
  acceptTokens,
  acceptsVideo,
  fileFits,
  kindOfAccept,
  matchesAccept,
  recordsAudio,
  uploadAccept,
  uploadChoices,
  uploadIntro,
  wrongFileMessage,
} from "./assetAccept.ts";

test("nothing accepted means everything fits", () => {
  assert.equal(matchesAccept("", { mimeType: "image/png", name: "a.png" }), true);
  assert.equal(matchesAccept(undefined, { mimeType: null, name: "" }), true);
});

test("a wildcard matches the type, an exact type matches exactly, parameters are ignored", () => {
  assert.equal(matchesAccept("audio/*", { mimeType: "audio/webm;codecs=opus", name: "a" }), true);
  assert.equal(matchesAccept("audio/*", { mimeType: "image/png", name: "a" }), false);
  assert.equal(matchesAccept("application/pdf", { mimeType: "application/pdf", name: "x.pdf" }), true);
  assert.equal(matchesAccept("application/pdf", { mimeType: "application/msword", name: "x.doc" }), false);
  assert.equal(matchesAccept("text/html", { mimeType: "TEXT/HTML; charset=utf-8", name: "p" }), true);
});

test("an ending matches the name, and is the only way an asset of unknown type fits", () => {
  assert.equal(matchesAccept(".fountain,.txt", { mimeType: "application/octet-stream", name: "Story.FOUNTAIN" }), true);
  assert.equal(matchesAccept(".fountain", { mimeType: null, name: "story.txt" }), false);
  assert.equal(matchesAccept("application/pdf", { mimeType: null, name: "x.pdf" }), false);
});

test("several tokens: any one is enough", () => {
  assert.equal(matchesAccept("text/html,.html", { mimeType: "text/plain", name: "page.html" }), true);
  assert.deepEqual(acceptTokens(" Audio/* , .MP3 ,, "), ["audio/*", ".mp3"]);
});

test("the upload dialog takes the field's accept, else the usual kinds", () => {
  assert.equal(uploadAccept("application/pdf"), "application/pdf");
  assert.match(uploadAccept(""), /image\/\*/);
});

test("a field's kind of file comes from its accept: one family is that kind, anything else is any", () => {
  assert.equal(kindOfAccept("audio/*"), "audio");
  assert.equal(kindOfAccept("image/png,image/jpeg"), "image");
  assert.equal(kindOfAccept("video/mp4,video/webm"), "video");
  assert.equal(kindOfAccept("audio/*,video/*"), "any"); // a transcript's source: a sound or a video
  assert.equal(kindOfAccept(".fountain,text/plain"), "any");
  assert.equal(kindOfAccept("video/mp4,image/gif"), "any"); // an overlay: a video or a picture
  assert.equal(kindOfAccept(""), "any");
  assert.equal(kindOfAccept(null), "any");
});

test("the upload dialog of a sound field talks about audio files, not pictures or the cropper", () => {
  const sound = uploadIntro("audio/*", "audio");
  assert.equal(
    sound,
    "A new audio file for this field: upload one, or record one. It is uploaded now, chosen here, and attached as audio when you save.",
  );
  assert.doesNotMatch(sound, /picture|cropper|image/i);
  assert.match(
    uploadIntro("image/*", "hero"),
    /^A new image for this field: upload one\. An image opens in the cropper/,
  );
  assert.match(
    uploadIntro("", "file"),
    /^A new file for this field: upload one, or record one\. An image opens in the cropper/,
  );
  assert.match(uploadIntro("application/pdf", "doc"), /^A new file for this field: upload one\. It is uploaded/);
});

test("a field that is not an entry's own (no role) does not promise an attachment on save", () => {
  const sound = uploadIntro("audio/*", null);
  assert.match(sound, /uploaded to your assets now and chosen here/);
  assert.doesNotMatch(sound, /attached|when you save/);
});

test("acceptsVideo: a field offers the camera when it takes video, or anything at all", () => {
  assert.equal(acceptsVideo("video/*"), true);
  assert.equal(acceptsVideo("audio/*,video/*"), true); // both buttons: record a sound or a video
  assert.equal(acceptsVideo("video/mp4,image/gif"), true);
  assert.equal(acceptsVideo(".mp4"), true);
  assert.equal(acceptsVideo(""), true); // takes anything
  assert.equal(acceptsVideo(null), true);
});

test("acceptsVideo: a sound-only or picture-and-document field gets no camera", () => {
  assert.equal(acceptsVideo("audio/*"), false); // keeps only the audio recorder
  assert.equal(acceptsVideo("image/*,application/pdf"), false);
});

// ---- uploadChoices: one rule for every upload surface ----

test("test_upload_choices_audio_only_records_audio_and_never_video", () => {
  for (const accept of ["audio/*", "audio/mpeg,audio/wav", ".mp3,.wav,.webm", "audio/*,.webm"]) {
    assert.deepEqual(
      uploadChoices(accept),
      { upload: "Upload an audio file", hint: "Audio files only", record: ["audio"] },
      accept,
    );
  }
});

test("test_upload_choices_video_only", () => {
  assert.deepEqual(uploadChoices("video/*"), { upload: "Upload a video", hint: "Video files only", record: ["video"] });
  assert.deepEqual(uploadChoices(".mp4,.mov").record, ["video"]);
});

test("test_upload_choices_image_only_has_no_recorder", () => {
  assert.deepEqual(uploadChoices("image/*"), { upload: "Upload an image", hint: "Images only", record: [] });
  assert.deepEqual(uploadChoices(".png,.jpg").record, []);
});

test("test_upload_choices_audio_and_video_offer_both_recorders", () => {
  assert.deepEqual(uploadChoices("audio/*,video/*"), {
    upload: "Upload a file",
    hint: "Audio or video files only",
    record: ["audio", "video"],
  });
  assert.deepEqual(uploadChoices(".webm").record, ["audio", "video"], "a bare .webm can be either");
});

test("test_upload_choices_documents_upload_only", () => {
  assert.deepEqual(uploadChoices("application/pdf"), { upload: "Upload a file", hint: "PDF files only", record: [] });
  assert.equal(uploadChoices("text/html,.html").hint, "HTML files only");
  assert.equal(uploadChoices("text/*,.fountain,.md,.txt").hint, "Text, .fountain or Markdown files only");
  assert.deepEqual(uploadChoices(".json").record, []);
});

test("test_upload_choices_mixed_media_and_documents", () => {
  assert.deepEqual(uploadChoices("image/*,application/pdf"), {
    upload: "Upload a file",
    hint: "Images or PDF files only",
    record: [],
  });
  assert.deepEqual(uploadChoices("video/mp4,image/gif"), {
    upload: "Upload a file",
    hint: "Images or video files only",
    record: ["video"],
  });
});

test("test_upload_choices_no_accept_offers_everything", () => {
  for (const accept of ["", null, undefined, " , "]) {
    assert.deepEqual(uploadChoices(accept), {
      upload: "Upload any file",
      hint: "Any file",
      record: ["audio", "video"],
    });
  }
});

test("test_upload_choices_several_at_once", () => {
  assert.deepEqual(uploadChoices(null, true), {
    upload: "Upload files",
    hint: "Any file; several at once",
    record: ["audio", "video"],
  });
  assert.equal(uploadChoices("audio/*", true).upload, "Upload audio files");
  assert.equal(uploadChoices("image/*", true).hint, "Images only; several at once");
});

test("test_accept_families", () => {
  assert.equal(acceptFamilies(""), null);
  assert.deepEqual(acceptFamilies("image/*,audio/*,application/pdf"), ["audio", "image", "document"]);
  assert.deepEqual(acceptFamilies(".webm,video/mp4"), ["video"]);
});

test("test_records_audio_follows_the_choices", () => {
  assert.equal(recordsAudio("audio/*"), true);
  assert.equal(recordsAudio(""), true);
  assert.equal(recordsAudio("video/*"), false);
  assert.equal(recordsAudio("image/*,application/pdf"), false, "a picture-and-document field has no microphone");
  assert.equal(acceptsVideo(".mp3,.wav,.webm"), false, "a sound list that names .webm stays sound only");
});

test("test_file_fits_and_the_one_wrong_type_message", () => {
  assert.equal(fileFits("audio/*", { name: "a.mp3", type: "audio/mpeg" }), true);
  assert.equal(fileFits("audio/*", { name: "clip.mov", type: "video/quicktime" }), false);
  assert.equal(fileFits("", { name: "x.bin", type: "" }), true);
  assert.equal(wrongFileMessage("audio/*", "clip.mov"), "clip.mov can't go here: audio files only.");
  assert.equal(wrongFileMessage("application/pdf", "a.png"), "a.png can't go here: PDF files only.");
});

test("a video field's dialog says it can record", () => {
  assert.match(uploadIntro("video/*", "clip"), /^A new video for this field: upload one, or record one\./);
});
