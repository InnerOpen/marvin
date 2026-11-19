// Whether an asset plays as a small video, and its poster (videoAsset.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { firstFrameSrc, isVideoAsset, videoPosterOf } from "./videoAsset.ts";

const clip = { id: "v1", publicUrl: "https://cdn/ws/2026/11/abc.mp4", mimeType: "video/mp4" };

describe("isVideoAsset", () => {
  test("test_video_mime_types_are_videos", () => {
    for (const mimeType of ["video/mp4", "video/quicktime", "video/webm", "VIDEO/MP4"]) assert.equal(isVideoAsset({ ...clip, mimeType }), true, mimeType);
  });

  test("test_pictures_sounds_and_documents_are_not_videos", () => {
    for (const mimeType of ["image/png", "audio/mpeg", "audio/webm", "application/pdf", "text/plain"]) assert.equal(isVideoAsset({ ...clip, mimeType }), false, mimeType);
  });

  test("test_a_sound_in_a_video_container_is_not_a_video", () => {
    const take = { ...clip, publicUrl: "https://cdn/take.webm", mimeType: "video/webm" };
    assert.equal(isVideoAsset({ ...take, role: "audio" }), false); // a voice line's take
    assert.equal(isVideoAsset({ ...take, metadataJson: { recording: { kind: "audio" } } }), false); // the audio recorder made it
  });

  test("test_the_video_recorders_take_is_a_video_whatever_its_role", () => {
    assert.equal(isVideoAsset({ ...clip, mimeType: "video/webm", role: "audio", metadataJson: { recording: { kind: "video" } } }), true);
  });

  test("test_without_a_type_the_file_ending_decides_and_webm_stays_a_sound", () => {
    assert.equal(isVideoAsset({ publicUrl: "https://cdn/shot.MOV?sig=1", mimeType: null }), true);
    assert.equal(isVideoAsset({ publicUrl: "https://cdn/take.webm", mimeType: "" }), false);
  });

  test("test_no_file_url_is_no_video", () => {
    assert.equal(isVideoAsset({ ...clip, publicUrl: null }), false);
    assert.equal(isVideoAsset(null), false);
  });
});

describe("videoPosterOf", () => {
  const still = { id: "p1", slug: "beat-04-still", publicUrl: "https://cdn/still.png", mimeType: "image/png" };

  test("test_a_poster_named_by_url_is_used_as_it_is", () => {
    assert.equal(videoPosterOf({ ...clip, metadataJson: { poster: "https://cdn/p.jpg" } }), "https://cdn/p.jpg");
    assert.equal(videoPosterOf({ ...clip, metadataJson: { poster: "/assets/p.jpg" } }), "/assets/p.jpg");
  });

  test("test_a_poster_named_by_asset_id_or_slug_is_found_among_the_siblings", () => {
    assert.equal(videoPosterOf({ ...clip, metadataJson: { poster_asset_id: "p1" } }, [clip, still]), "https://cdn/still.png");
    assert.equal(videoPosterOf({ ...clip, metadataJson: { poster: "beat-04-still" } }, [still]), "https://cdn/still.png");
  });

  test("test_no_poster_when_none_is_named_or_it_is_not_a_picture_at_hand", () => {
    assert.equal(videoPosterOf(clip, [still]), null);
    assert.equal(videoPosterOf({ ...clip, metadataJson: { poster_id: "p1" } }, []), null); // not on this page
    assert.equal(videoPosterOf({ ...clip, metadataJson: { poster: "v1" } }, [clip]), null); // a video is no poster
    assert.equal(videoPosterOf({ ...clip, metadataJson: { poster: "javascript:alert(1)" } }, []), null);
  });
});

describe("firstFrameSrc", () => {
  test("test_first_frame_fragment_is_added_once", () => {
    assert.equal(firstFrameSrc("https://cdn/a.mp4?sig=x"), "https://cdn/a.mp4?sig=x#t=0.001");
    assert.equal(firstFrameSrc("https://cdn/a.mp4#t=5"), "https://cdn/a.mp4#t=5");
  });
});
