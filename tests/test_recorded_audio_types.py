"""Recorded and phone audio is filed as audio (services/assets/metadata_extractor.py).

A browser's recorder (components/AudioRecorder.astro) makes WebM/Opus, MP4/AAC or Ogg/Opus; a phone's voice memo is
an .m4a. The type comes from the file's extension, which can't tell a sound-only .webm from a video, so the upload's
own part type settles that one container, and only that one. Expected types are asserted as the asset type where the
host's mime.types decides the exact name (``.opus`` is ``audio/ogg`` on one box and ``audio/opus`` on another).
"""

# ruff: noqa: F811 — `workspace` is a fixture, not a redefinition
import uuid

import pytest

from marvin.services.assets.metadata_extractor import AssetMetadataExtractor
from tests import test_content_role_gates as gates
from tests.test_content_role_gates import P, workspace  # noqa: F401 — fixture


def _extract(tmp_path, name: str, declared: str | None = None):
    path = tmp_path / name
    path.write_bytes(b"not really audio")
    return AssetMetadataExtractor().extract_metadata(path, declared)


@pytest.mark.parametrize("name", ["take.m4a", "take.ogg", "take.oga", "take.opus", "take.weba", "take.wav", "take.flac"])
def test_recorder_and_phone_extensions_are_audio(tmp_path, name):
    assert _extract(tmp_path, name).asset_type == "audio"


@pytest.mark.parametrize("mime", ["audio/mp4", "audio/x-m4a", "audio/opus", "audio/x-wav"])
def test_recorder_mime_types_are_audio(mime):
    assert AssetMetadataExtractor()._classify_asset_type(mime) == "audio"


def test_a_webm_sent_as_audio_is_audio(tmp_path):
    made = _extract(tmp_path, "take.webm", "audio/webm;codecs=opus")
    assert (made.mime_type, made.asset_type) == ("audio/webm", "audio")


def test_a_webm_without_a_part_type_stays_a_video(tmp_path):
    made = _extract(tmp_path, "clip.webm")
    assert (made.mime_type, made.asset_type) == ("video/webm", "video")


@pytest.mark.parametrize("declared", ["video/webm", "audio/mpeg", "application/pdf", "AUDIO/OGG"])
def test_a_part_type_of_another_container_is_ignored(tmp_path, declared):
    assert _extract(tmp_path, "clip.webm", declared).mime_type == "video/webm"


def test_an_upload_of_a_recorded_webm_is_an_audio_asset(workspace):
    author = gates._sign_in(workspace, gates.A)
    files = {"file": ("line-007-take-03.webm", b"\x1aE\xdf\xa3 recorded", "audio/webm;codecs=opus")}
    res = author.post(f"{P}/assets/upload", files=files, data={"slug": f"take-{uuid.uuid4().hex[:6]}", "name": "Take 3"})
    assert res.status_code == 201, res.text
    assert (res.json()["assetType"], res.json()["mimeType"]) == ("audio", "audio/webm")
