"""A picture goes to the AI with the type its bytes say, not its stored label: a PNG version saved as image/jpeg made
Anthropic refuse every look at it ("specified using image/jpeg … appears to be image/png")."""

import io

from PIL import Image

from marvin.services.ai.context import ContextBuilder, sniff_image_mime


def _bytes(fmt: str) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (4, 4), "navy").save(out, format=fmt)
    return out.getvalue()


def test_the_first_bytes_name_the_type():
    assert sniff_image_mime(_bytes("PNG")) == "image/png"
    assert sniff_image_mime(_bytes("JPEG")) == "image/jpeg"
    assert sniff_image_mime(_bytes("GIF")) == "image/gif"
    assert sniff_image_mime(_bytes("WEBP")) == "image/webp"
    assert sniff_image_mime(b"%PDF-1.7 ...") is None


def test_a_png_stored_as_jpeg_is_sent_as_png(monkeypatch):
    png = _bytes("PNG")

    class Storage:
        def get(self, key):
            return io.BytesIO(png)

    monkeypatch.setattr("marvin.services.storage.provider_factory.provider_for", lambda _name=None: Storage())
    builder = ContextBuilder.__new__(ContextBuilder)
    builder._ctx = type("Ctx", (), {"assets": [{"mime_type": "image/jpeg", "storage_key": "lib/x", "storage_provider": "local"}]})()
    builder.with_asset_images(limit=1)
    asset = builder._ctx.assets[0]
    assert asset["mime_type"] == "image/png" and asset["image_data"]
