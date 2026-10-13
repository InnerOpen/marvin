"""Media embeds: registry/matcher, embed code, HTML builder, resolver, cache, extraction, publishing,
the ``embed`` field type, the admin endpoints, the save-time listener and the agent tools.

oEmbed replies are real responses recorded 2026-10-05 into ``tests/fixtures/media_embeds`` (see the
provider registry's docstring for which endpoints were checked). No test reaches the network: the suite
sets ``MEDIA_EMBEDS_FETCH_ENABLED=False`` and every resolver test passes a fake HTTP client.
"""

import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.services.media_embeds import resolver
from marvin.services.media_embeds.extract import bare_urls, entry_embed_urls
from marvin.services.media_embeds.html import attrs, player_html
from marvin.services.media_embeds.matcher import match_url, url_from_input
from marvin.services.media_embeds.providers import PROVIDERS, frame_sources

FIXTURES = Path(__file__).parent / "fixtures" / "media_embeds"


class FakeHttp:
    """Answers oEmbed GETs from recorded fixtures; records every URL asked for."""

    def __init__(self, status: int = 200, body: bytes | str | None = None, fixture: str | None = None, exc: Exception | None = None):
        self.status = status
        self.body = (FIXTURES / fixture).read_bytes() if fixture else (body.encode() if isinstance(body, str) else (body or b"{}"))
        self.exc = exc
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, *, headers=None, timeout=15):
        self.calls.append((url, dict(headers or {})))
        if self.exc:
            raise self.exc
        return SimpleNamespace(status_code=self.status, content=self.body, headers={})


# --------------------------------------------------------------------------------------------------
# Registry + matcher


@pytest.mark.parametrize(
    "url, provider, kind, canonical, src",
    [
        (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "youtube",
            "video",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
        ),
        ("https://youtu.be/dQw4w9WgXcQ?t=1m30s", "youtube", "video", None, "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?start=90"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ&feature=share", "youtube", "video", None, "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "youtube", "video", "https://www.youtube.com/shorts/dQw4w9WgXcQ", None),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "youtube", "video", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", None),
        (
            "https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI",
            "youtube",
            "playlist",
            None,
            "https://www.youtube-nocookie.com/embed/videoseries?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI",
        ),
        ("https://vimeo.com/1084537", "vimeo", "video", "https://vimeo.com/1084537", "https://player.vimeo.com/video/1084537?dnt=1"),
        ("https://vimeo.com/123456/abcdef1234", "vimeo", "video", None, "https://player.vimeo.com/video/123456?dnt=1&h=abcdef1234"),
        ("https://player.vimeo.com/video/1084537?h=abcdef12", "vimeo", "video", "https://vimeo.com/1084537/abcdef12", None),
        (
            "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT?si=abc",
            "spotify",
            "audio",
            "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
            "https://open.spotify.com/embed/track/4cOdK2wGLETKBW3PvgPWqT",
        ),
        ("https://open.spotify.com/intl-de/album/4cOdK2wGLETKBW3PvgPWqT", "spotify", "playlist", None, None),
        ("https://open.spotify.com/episode/4cOdK2wGLETKBW3PvgPWqT", "spotify", "podcast", None, None),
        ("https://soundcloud.com/forss/flickermood", "soundcloud", "audio", "https://soundcloud.com/forss/flickermood", None),
        ("https://soundcloud.com/forss/sets/soulhack", "soundcloud", "playlist", None, None),
        (
            "https://music.apple.com/us/album/1989-taylors-version/1708308989",
            "apple_music",
            "playlist",
            None,
            "https://embed.music.apple.com/us/album/1989-taylors-version/1708308989",
        ),
        ("https://music.apple.com/us/album/x/1708308989?i=1708309001", "apple_music", "audio", None, None),
        (
            "https://podcasts.apple.com/us/podcast/the-daily/id1200361736",
            "apple_podcasts",
            "podcast",
            None,
            "https://embed.podcasts.apple.com/us/podcast/the-daily/id1200361736",
        ),
        ("https://tidal.com/browse/track/77646168", "tidal", "audio", None, "https://embed.tidal.com/tracks/77646168"),
        ("https://listen.tidal.com/album/77646160", "tidal", "playlist", "https://tidal.com/browse/album/77646160", None),
        ("https://share.transistor.fm/s/9c22a01c", "transistor", "podcast", None, "https://share.transistor.fm/e/9c22a01c"),
        ("https://player.simplecast.com/e96ea7f2-f7bc-4362-a3f4-368212abfaf1", "simplecast", "podcast", None, None),
        (
            "https://bandcamp.com/EmbeddedPlayer/album=123456/size=large/tracklist=false",
            "bandcamp",
            "playlist",
            "https://bandcamp.com/EmbeddedPlayer/album=123456",
            None,
        ),
    ],
)
def test_supported_url_forms(url, provider, kind, canonical, src):
    m = match_url(url)
    assert m is not None, url
    assert (m.provider.key, m.target.kind) == (provider, kind)
    assert m.url == url
    if canonical:
        assert m.target.canonical_url == canonical
    if src:
        assert m.target.src == src
    if m.target.src:
        assert m.provider.frame_host_ok(m.target.src)


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
        "https://notyoutube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com@evil.example/watch?v=dQw4w9WgXcQ",
        "https://user:pw@www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com:8443/watch?v=dQw4w9WgXcQ",
        "https://evil.example/?u=https://youtu.be/dQw4w9WgXcQ",
        "javascript:alert(1)//https://youtu.be/dQw4w9WgXcQ",
        "ftp://youtu.be/dQw4w9WgXcQ",
        "https://open.spotify.com.evil.example/track/4cOdK2wGLETKBW3PvgPWqT",
        "https://fakebandcamp.com/album/x",
        "https://bandcamp.com.evil.example/EmbeddedPlayer/album=1",
        "https://evilsimplecast.com/episodes/x",
        "https://simplecast.com.evil.example/episodes/x",
        "https://share.transistor.fm.evil.example/s/9c22a01c",
        "https://xvimeo.com/1084537",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/about",
        "https://vimeo.com/channels/staffpicks",
        "https://soundcloud.com/forss",
        "https://soundcloud.com/discover/sets/x",
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ"onload="x',
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ <b>",
    ],
)
def test_look_alikes_and_non_media_links_are_rejected(url):
    assert match_url(url) is None


def test_bandcamp_page_link_is_link_only_and_simplecast_page_needs_oembed():
    bc = match_url("https://artist.bandcamp.com/album/some-record")
    assert bc and bc.provider.key == "bandcamp" and bc.target.src is None
    sc = match_url("https://uibreakfast.simplecast.com/episodes/better-done-than-perfect")
    assert sc and sc.provider.key == "simplecast" and sc.target.src is None
    assert PROVIDERS["bandcamp"].link_only is True


def test_frame_sources_are_https_origins_of_every_provider():
    sources = frame_sources()
    assert "https://www.youtube-nocookie.com" in sources and "https://player.simplecast.com" in sources
    assert all(s.startswith("https://") and "/" not in s[len("https://") :] for s in sources)
    assert "https://www.youtube.com" not in sources  # players only ever load from youtube-nocookie


# --------------------------------------------------------------------------------------------------
# Embed code → link


def test_embed_code_reduces_to_the_canonical_link():
    yt = '<iframe width="560" height="315" src="https://www.youtube.com/embed/dQw4w9WgXcQ?si=x" title="YouTube video player"></iframe>'
    assert url_from_input(yt) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    sc = (
        '<iframe width="100%" height="166" scrolling="no" src="https://w.soundcloud.com/player/?url=https%3A//api.soundcloud.com/tracks/293'
        '&amp;color=%23ff5500"></iframe><div><a href="https://soundcloud.com/forss" title="Forss">Forss</a> · '
        '<a href="https://soundcloud.com/forss/flickermood" title="Flickermood">Flickermood</a></div>'
    )
    assert url_from_input(sc) == "https://soundcloud.com/forss/flickermood"
    bc = (
        '<iframe style="border: 0; width: 350px; height: 470px;" src="https://bandcamp.com/EmbeddedPlayer/album=987654/size=large/'
        'bgcol=ffffff/linkcol=0687f5/tracklist=false/transparent=true/" seamless><a href="https://artist.bandcamp.com/album/rec">Rec</a></iframe>'
    )
    assert url_from_input(bc) == "https://bandcamp.com/EmbeddedPlayer/album=987654"
    assert url_from_input("  https://youtu.be/dQw4w9WgXcQ  ") == "https://youtu.be/dQw4w9WgXcQ"


def test_embed_code_from_an_unknown_host_is_refused():
    assert url_from_input('<iframe src="https://evil.example/embed/dQw4w9WgXcQ"></iframe>') is None
    assert url_from_input("<script>alert(1)</script>") is None
    assert url_from_input("not a link") is None


# --------------------------------------------------------------------------------------------------
# HTML builder


def _iframe(**over):
    base = {
        "src": "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
        "title": 'A "quoted" <title> & more',
        "allow": "autoplay; fullscreen",
        "sandbox": "allow-scripts allow-same-origin",
        "referrerpolicy": "strict-origin-when-cross-origin",
        "aspectRatio": "16/9",
        "height": None,
    }
    base.update(over)
    return base


def _player(mode, **over):
    return player_html(
        provider="youtube",
        provider_name="YouTube",
        kind="video",
        iframe=_iframe(**over),
        frame_hosts=["www.youtube-nocookie.com"],
        link_href="https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1",
        link_title='Title "x" <y>',
        title='Title "x" <y>',
        mode=mode,
        consent_text="Loads {provider} — <b>cookies</b>",
    )


def test_attrs_escapes_every_value():
    assert attrs({"a": '"><script>', "b": True, "c": None, "d": False}) == ' a="&quot;&gt;&lt;script&gt;" b'


def test_direct_html_is_the_figure_with_the_iframe():
    out = _player("direct")
    assert out.startswith('<figure class="marvin-embed marvin-embed--video" data-provider="youtube" style="--marvin-embed-aspect:16/9"><iframe ')
    assert 'src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"' in out
    assert 'title="A &quot;quoted&quot; &lt;title&gt; &amp; more"' in out
    assert 'loading="lazy"' in out and 'referrerpolicy="strict-origin-when-cross-origin"' in out
    assert "allowfullscreen" not in out and "<script" not in out


def test_click_to_load_html_is_a_facade_with_a_link_fallback():
    out = _player("click_to_load")
    assert out.startswith('<figure class="marvin-embed marvin-embed--video marvin-embed--facade" data-provider="youtube"')
    assert "<iframe" not in out  # nothing third-party until the click
    assert '<button type="button" class="marvin-embed__load" data-marvin-embed-src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"' in out
    assert 'data-marvin-embed-hosts="[&quot;www.youtube-nocookie.com&quot;]"' in out
    assert "Loads YouTube — &lt;b&gt;cookies&lt;/b&gt;" in out  # {provider} substituted, text escaped
    assert '<a class="marvin-embed__link" href="https://www.youtube.com/watch?v=dQw4w9WgXcQ&amp;t=1" rel="noopener noreferrer">' in out
    import html as _html
    import re

    attrs_json = _html.unescape(re.search(r'data-marvin-embed-attrs="([^"]*)"', out).group(1))
    loaded = json.loads(attrs_json)
    assert set(loaded) == {"src", "title", "allow", "sandbox", "referrerpolicy", "loading"}
    assert all(isinstance(v, str) for v in loaded.values())
    assert loaded["title"] == 'A "quoted" <title> & more'


def test_fixed_height_players_size_by_height():
    out = _player("direct", aspectRatio=None, height=352)
    assert 'style="--marvin-embed-height:352px"' in out


# --------------------------------------------------------------------------------------------------
# Resolver (recorded fixtures)


@pytest.mark.parametrize(
    "url, fixture, title",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube.json", "Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)"),
        ("https://vimeo.com/1084537", "vimeo.json", "Big Buck Bunny"),
        ("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT", "spotify.json", "Never Gonna Give You Up"),
        ("https://soundcloud.com/forss/flickermood", "soundcloud.json", "Flickermood by Forss"),
        ("https://podcasts.apple.com/us/podcast/the-daily/id1200361736", "apple_podcasts.json", "The Daily"),
        ("https://music.apple.com/us/album/1989-taylors-version/1708308989", "apple_music.json", "1989 (Taylor's Version)"),
        ("https://tidal.com/browse/track/77646168", "tidal.json", None),
        ("https://share.transistor.fm/s/9c22a01c", "transistor.json", "What is Transistor's secret weapon?"),
    ],
)
def test_resolve_with_recorded_oembed(url, fixture, title):
    http = FakeHttp(fixture=fixture)
    r = resolver.resolve(url, http=http, fetch=True)
    assert r.status == "ok" and r.settled and r.error is None
    assert r.title == title
    assert r.embed_src == match_url(url).target.src  # Marvin's own src, never the provider's html
    endpoint, headers = http.calls[0]
    assert endpoint.startswith("https://") and headers["User-Agent"] == "marvin-cms/embeds"


def test_simplecast_player_id_comes_from_the_oembed_src():
    url = "https://uibreakfast.simplecast.com/episodes/better-done-than-perfect-marketing-channels-programs-with-asia-orangio"
    http = FakeHttp(fixture="simplecast.json")
    r = resolver.resolve(url, http=http, fetch=True)
    assert r.status == "ok"
    assert r.embed_src == "https://player.simplecast.com/e96ea7f2-f7bc-4362-a3f4-368212abfaf1"
    assert http.calls[0][0].startswith("https://api.simplecast.com/oembed?url=https%3A%2F%2Fuibreakfast.simplecast.com")


def test_an_oembed_src_on_a_foreign_host_is_never_used():
    url = "https://uibreakfast.simplecast.com/episodes/x"
    body = json.dumps({"title": "T", "html": '<iframe src="https://evil.example/e96ea7f2-f7bc-4362-a3f4-368212abfaf1"></iframe>'})
    r = resolver.resolve(url, http=FakeHttp(body=body), fetch=True)
    assert r.status == "link" and r.embed_src is None


def test_missing_media_is_unavailable():
    r = resolver.resolve("https://vimeo.com/76979871", http=FakeHttp(status=404, fixture="vimeo_404.html"), fetch=True)
    assert r.status == "unavailable" and r.embed_src is None and r.settled


def test_a_transient_failure_keeps_the_link_built_player_but_is_not_settled():
    r = resolver.resolve("https://vimeo.com/1084537", http=FakeHttp(status=503, body="down"), fetch=True)
    assert r.status == "ok" and r.embed_src and not r.settled and "503" in r.error
    r = resolver.resolve("https://vimeo.com/1084537", http=FakeHttp(exc=TimeoutError("slow")), fetch=True)
    assert r.status == "ok" and not r.settled
    r = resolver.resolve("https://vimeo.com/1084537", http=FakeHttp(body="<html>"), fetch=True)
    assert r.status == "ok" and not r.settled


def test_bandcamp_and_disabled_fetch_make_no_call():
    http = FakeHttp(fixture="youtube.json")
    assert resolver.resolve("https://artist.bandcamp.com/album/x", http=http, fetch=True).status == "link"
    assert resolver.resolve("https://youtu.be/dQw4w9WgXcQ", http=http, fetch=False).status == "ok"
    assert http.calls == []
    assert resolver.resolve("https://example.com/video", http=http, fetch=True) is None


def test_core_http_client_imports_without_the_integration_sdk():
    from marvin.services.integrations.http_client import MarvinHttpHelper, Response

    assert Response(200).ok and MarvinHttpHelper(max_bytes=10)._max_bytes == 10


# --------------------------------------------------------------------------------------------------
# Extraction


YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "markdown, expected",
    [
        (f"Intro.\n\n{YT}\n\nOutro.", [YT]),
        (f"{YT}", [YT]),
        (f"   {YT}   ", [YT]),
        (f"## Watch\n{YT}\n\nMore", [YT]),
        (f"<{YT}>", []),
        (f"[the video]({YT})", []),
        (f"Watch {YT} now.", []),
        (f"Intro line\n{YT}\n\nmore", []),
        (f"{YT}\n---", []),
        (f"- {YT}", []),
        (f"> {YT}", []),
        (f"    {YT}", []),
        (f"```\n{YT}\n```", []),
        (f"~~~md\n\n{YT}\n\n~~~", []),
        (f"{YT}.", []),
        (f"{YT}\n\n{YT}", [YT]),
    ],
)
def test_bare_urls(markdown, expected):
    assert bare_urls(markdown) == expected


def test_the_key_is_the_url_as_written():
    written = "https://youtu.be/dQw4w9WgXcQ?t=42"
    schema = {"fields": [{"key": "body", "label": "Body", "type": "markdown"}]}
    assert entry_embed_urls(schema, {"body": f"x\n\n{written}\n"}) == [written]


def test_auto_embed_false_and_embed_fields():
    schema = {
        "fields": [
            {"key": "body", "label": "Body", "type": "markdown", "autoEmbed": False},
            {"key": "notes", "label": "Notes", "type": "markdown"},
            {"key": "player", "label": "Player", "type": "embed", "providers": ["vimeo"]},
            {"key": "any", "label": "Any", "type": "embed"},
        ]
    }
    data = {
        "body": YT,
        "notes": "https://example.com/not-media\n\nhttps://vimeo.com/1084537",
        "player": YT,  # not an allowed provider for this field
        "any": "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
    }
    assert entry_embed_urls(schema, data) == ["https://vimeo.com/1084537", "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"]
    assert entry_embed_urls(None, data) == [] and entry_embed_urls(schema, None) == []


# --------------------------------------------------------------------------------------------------
# Schema + validation


def test_embed_field_schema_and_validation():
    from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition
    from marvin.services.content_validator import ContentValidationError, validate_entry_content

    schema = EntryTypeSchemaDefinition.model_validate(
        {
            "fields": [
                {"key": "body", "label": "Body", "type": "markdown", "autoEmbed": False},
                {"key": "video", "label": "Video", "type": "embed", "providers": ["youtube", "vimeo"]},
            ]
        }
    )
    assert schema.get_field("body").auto_embed is False
    validate_entry_content(schema, {"video": YT})
    validate_entry_content(schema, {"video": ""})
    with pytest.raises(ContentValidationError, match="Spotify links aren't allowed"):
        validate_entry_content(schema, {"video": "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"})
    with pytest.raises(ContentValidationError, match="Not a supported media link"):
        validate_entry_content(schema, {"video": "https://example.com/x"})
    with pytest.raises(ContentValidationError):
        validate_entry_content(schema, {"video": 3})
    with pytest.raises(ValueError, match="Unknown media providers"):
        EntryTypeSchemaDefinition.model_validate({"fields": [{"key": "v", "label": "V", "type": "embed", "providers": ["myspace"]}]})
    assert EntryTypeSchemaDefinition.model_validate({"fields": [{"key": "b", "label": "B", "type": "markdown"}]}).fields[0].auto_embed is True


def test_compose_never_invites_invented_media_links():
    from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition
    from marvin.services.ai.compose import entry_type_to_output_schema

    schema = EntryTypeSchemaDefinition.model_validate({"fields": [{"key": "video", "label": "Video", "type": "embed"}]})
    prop = entry_type_to_output_schema(schema, "Episode")["properties"]["video"]
    assert prop["type"] == "string" and "copied exactly from the brief" in prop["description"]


# --------------------------------------------------------------------------------------------------
# Publishing (DB-backed)


class _AllowAll:
    def require_permission(self, *_):
        return None

    def require_any_permission(self, *_):
        return None

    def has_permission(self, *_):
        return False


@fixture
def site(db_session):
    """A workspace with a published entry carrying a bare YouTube link, a link in brackets, and an embed field."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Entries, EntryTypes

    gid = uuid.uuid4()
    slug = f"embeds-{gid.hex[:8]}"
    group = Groups(session=db_session, name=slug, slug=slug)
    group.id = gid
    db_session.add(group)
    db_session.flush()
    schema = {
        "fields": [
            {"key": "body", "label": "Body", "type": "markdown"},
            {"key": "player", "label": "Player", "type": "embed"},
        ]
    }
    et = EntryTypes(session=db_session, group_id=gid, name="Post", slug="post", schema_json=schema)
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()
    body = f"Hello.\n\n{YT}\n\nAs a link: [watch]({YT}) and <https://vimeo.com/1084537>.\n\nhttps://artist.bandcamp.com/album/x\n"
    entry = Entries(
        session=db_session,
        group_id=gid,
        entry_type_id=et.id,
        title="Post",
        slug=f"post-{gid.hex[:8]}",
        status="published",
        data_json={"body": body, "player": "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"},
    )
    db_session.add(entry)
    db_session.commit()
    yield SimpleNamespace(group=group, gid=gid, entry=entry, et=et)

    from marvin.db.models.groups import GroupPreferencesModel
    from marvin.db.models.platform import MediaEmbedCacheModel
    from marvin.services.media_embeds.cache import url_hash

    db_session.rollback()
    db_session.query(MediaEmbedCacheModel).filter(
        MediaEmbedCacheModel.url_hash.in_([url_hash(u) for u in (YT, "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT")])
    ).delete(synchronize_session=False)
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.query(GroupPreferencesModel).filter(GroupPreferencesModel.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


@fixture
def no_network(monkeypatch):
    """Fail the test if anything on the publishing read path tries to reach a provider — even with fetching on."""

    def boom(*_a, **_k):
        raise AssertionError("publishing must not call out")

    monkeypatch.setattr(resolver, "fetch_enabled", lambda: True)
    monkeypatch.setattr(resolver, "default_http", boom)
    monkeypatch.setattr("marvin.services.integrations.http_client.MarvinHttpHelper.get", boom)


def _ctx(s):
    return (None, s.group, _AllowAll())


def _get(db_session, s):
    from marvin.routes.publish import publishing_controller as pub

    return asyncio.run(pub.get_published_entry(slug=s.entry.slug, context=_ctx(s), session=db_session))


def _list(db_session, s):
    from marvin.routes.publish import publishing_controller as pub

    return asyncio.run(
        pub.list_published_entries(
            context=_ctx(s), session=db_session, entry_type=None, collection=None, tag=None, slug=None, updated_since=None, limit=50, offset=0
        )
    )


def test_published_entry_and_list_item_carry_embeds_without_calling_out(db_session, site, no_network):
    detail = _get(db_session, site)
    item = _list(db_session, site).data[0]
    for got in (detail, item):
        assert set(got.embeds) == {YT, "https://artist.bandcamp.com/album/x", "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"}
        yt = got.embeds[YT]
        assert (yt.provider, yt.provider_name, yt.kind, yt.status) == ("youtube", "YouTube", "video", "ok")
        assert yt.iframe.src == "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ" and yt.iframe.aspect_ratio == "16/9"
        assert "marvin-embed--facade" in yt.html  # click_to_load is the default
        bc = got.embeds["https://artist.bandcamp.com/album/x"]
        assert bc.status == "link" and bc.iframe is None and bc.html.startswith('<a class="marvin-embed-link"')
        sp = got.embeds["https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"]
        assert sp.iframe.height == 152 and sp.iframe.aspect_ratio is None
    # Stored markdown is never rewritten.
    assert detail.data["body"].startswith("Hello.\n\nhttps://www.youtube.com/watch")


def test_wire_format_is_camel_case(db_session, site, no_network):
    dumped = _get(db_session, site).model_dump(by_alias=True)
    yt = dumped["embeds"][YT]
    assert {
        "url",
        "canonicalUrl",
        "provider",
        "providerName",
        "kind",
        "status",
        "title",
        "authorName",
        "thumbnailUrl",
        "iframe",
        "link",
        "html",
    } <= set(yt)
    assert set(yt["iframe"]) == {"src", "title", "allow", "sandbox", "referrerpolicy", "aspectRatio", "height"}
    assert set(yt["link"]) == {"href", "title", "providerName"}


def test_cached_details_and_site_mode_flow_into_the_html(db_session, site, no_network):
    from marvin.db.models.groups import GroupPreferencesModel
    from marvin.services.media_embeds.cache import store

    store(
        db_session,
        resolver.ResolvedEmbed(
            url=YT,
            provider="youtube",
            kind="video",
            status="ok",
            canonical_url=YT,
            embed_src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
            title="Never <Gonna>",
            aspect_ratio="16/9",
            settled=True,
        ),
    )
    prefs = db_session.query(GroupPreferencesModel).filter_by(group_id=site.gid).first()
    if prefs is None:
        prefs = GroupPreferencesModel(session=db_session, group_id=site.gid)
        db_session.add(prefs)
    prefs.site_metadata_json = {"embeds": {"mode": "direct", "consentText": "Custom"}}
    db_session.commit()

    yt = _get(db_session, site).embeds[YT]
    assert yt.title == "Never <Gonna>" and yt.link.title == "Never <Gonna>"
    assert yt.html.startswith('<figure class="marvin-embed marvin-embed--video" data-provider="youtube"') and "<iframe" in yt.html
    assert "Never &lt;Gonna&gt;" in yt.html

    from marvin.routes.publish import publishing_controller as pub

    site_info = asyncio.run(pub.get_site_configuration(context=_ctx(site), session=db_session))
    dumped = site_info.model_dump(by_alias=True)["site"]["embeds"]
    assert dumped["mode"] == "direct" and dumped["consentText"] == "Custom"
    assert "https://www.youtube-nocookie.com" in dumped["frameSources"]


def test_a_cached_src_off_the_providers_frame_hosts_is_dropped(db_session, site, no_network):
    from marvin.services.media_embeds.cache import store

    store(
        db_session,
        resolver.ResolvedEmbed(
            url=YT, provider="youtube", kind="video", status="ok", canonical_url=YT, embed_src="https://evil.example/x", settled=True
        ),
    )
    yt = _get(db_session, site).embeds[YT]
    assert yt.status == "link" and yt.iframe is None and "evil.example" not in yt.html


def test_site_embeds_defaults():
    from marvin.services.media_embeds.publish import site_embeds

    d = site_embeds(None)
    assert d.mode == "click_to_load" and "{provider}" in d.consent_text and d.frame_sources == frame_sources()
    assert site_embeds({"embeds": {"mode": "bogus"}}).mode == "click_to_load"
    assert site_embeds({"embeds": {"consent_text": "  x "}}).consent_text == "x"


# --------------------------------------------------------------------------------------------------
# Cache + listener


def test_listener_warms_the_cache_on_save(db_session, site, monkeypatch):
    from marvin.db.models.platform import MediaEmbedCacheModel
    from marvin.services.event_bus_service.event_bus_listener import MediaEmbedReactionListener
    from marvin.services.event_bus_service.event_types import EventTypes
    from marvin.services.media_embeds.cache import cached

    http = FakeHttp(fixture="youtube.json")
    monkeypatch.setattr(resolver, "fetch_enabled", lambda: True)
    monkeypatch.setattr(resolver, "default_http", lambda: http)

    listener = MediaEmbedReactionListener(site.gid)
    event = SimpleNamespace(event_type=EventTypes.entry_updated, document_data=SimpleNamespace(entry_id=site.entry.id), entity_id=None)
    assert listener.get_subscribers(event) == ["media_embeds"]
    assert listener.get_subscribers(SimpleNamespace(event_type=EventTypes.entry_deleted)) == []
    listener.publish_to_subscribers(event, ["media_embeds"])

    rows = cached(db_session, [YT, "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"])
    assert rows[YT].status == "ok" and rows[YT].title.startswith("Rick Astley")
    assert rows[YT].expires_at > rows[YT].fetched_at
    asked = len(http.calls)
    listener.publish_to_subscribers(event, ["media_embeds"])  # fresh rows → no second lookup
    assert len(http.calls) == asked
    assert db_session.query(MediaEmbedCacheModel).filter(MediaEmbedCacheModel.url == YT).count() == 1


def test_warm_is_capped(db_session, monkeypatch):
    from marvin.services.media_embeds.cache import warm

    seen = []
    monkeypatch.setattr("marvin.services.media_embeds.cache.resolve", lambda u, http=None: seen.append(u))
    warm(db_session, [f"https://vimeo.com/{1000 + i}" for i in range(30)], limit=20)
    assert len(seen) == 20


# --------------------------------------------------------------------------------------------------
# Admin endpoints


@fixture
def member(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    slug = f"embadm-{gid.hex[:8]}"
    group = Groups(session=db_session, name=slug, slug=slug)
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=slug,
            email=f"{slug}@t.test",
            full_name="E",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )
    db_session.commit()
    yield SimpleNamespace(gid=gid, uid=uid, slug=slug)
    from marvin.app import app
    from marvin.core.dependencies import get_current_user
    from marvin.db.models.platform import SubmissionRateLimits

    app.dependency_overrides.pop(get_current_user, None)
    db_session.rollback()
    db_session.query(SubmissionRateLimits).filter(SubmissionRateLimits.subject_id == uid).delete()
    db_session.query(Users).filter(Users.id == uid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _sign_in(m, role):
    from marvin.app import app
    from marvin.core.dependencies import get_current_user
    from marvin.db.models.users.roles import PlatformRole

    members = [SimpleNamespace(group_id=m.gid, workspace_role=role)]
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=m.uid,
        group_id=m.gid,
        active_group_id=m.gid,
        admin=False,
        is_superuser=False,
        full_name="E",
        email=f"{m.slug}@t.test",
        platform_role=PlatformRole.NONE,
        workspace_memberships=members,
        get_workspace_role=lambda group_id: role if str(group_id) == str(m.gid) else None,
    )
    return TestClient(app)


def test_providers_endpoint_lists_the_registry(member):
    from marvin.db.models.users.roles import WorkspaceRole

    r = _sign_in(member, WorkspaceRole.VIEWER).get("/api/platform/media-embeds/providers")
    assert r.status_code == 200
    body = r.json()
    keys = [p["key"] for p in body["providers"]]
    assert keys == list(PROVIDERS)
    bandcamp = next(p for p in body["providers"] if p["key"] == "bandcamp")
    assert bandcamp["linkOnly"] is True and "*.bandcamp.com" in bandcamp["hosts"]
    assert body["frameSources"] == frame_sources()


def test_resolve_is_author_and_above_and_rate_limited(member, monkeypatch):
    from marvin.db.models.users.roles import WorkspaceRole
    from marvin.routes.platform import media_embeds_controller as ctl

    path = "/api/platform/media-embeds/resolve"
    assert _sign_in(member, WorkspaceRole.VIEWER).post(path, json={"input": YT}).status_code == 403

    client = _sign_in(member, WorkspaceRole.AUTHOR)
    code = '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
    r = client.post(path, json={"input": code})
    assert r.status_code == 200
    body = r.json()
    assert body["url"] == YT and body["embed"]["status"] == "ok" and body["error"] is None
    assert "<iframe" in body["embed"]["html"]  # the editor preview defaults to the direct player

    r = client.post(path, json={"input": "https://example.com/nope"})
    assert r.status_code == 200 and r.json()["url"] is None and "Not a supported" in r.json()["error"]

    monkeypatch.setattr(ctl, "RESOLVE_LIMIT", 3)
    statuses = [client.post(path, json={"input": YT}).status_code for _ in range(3)]
    assert statuses[-1] == 429


# --------------------------------------------------------------------------------------------------
# Agent tools


def test_add_embed_stages_a_suggestion_and_is_idempotent(db_session, site):
    from marvin.db.models.platform import Entries
    from marvin.services.ai.tools import get_tool
    from marvin.services.ai.tools.base import ToolContext

    spec = get_tool("add_embed")
    assert spec.read_only is False and spec.min_role == 3  # EDITOR
    ctx = ToolContext(session=db_session, group_id=site.gid)
    vimeo = "https://vimeo.com/1084537"
    before = dict(site.entry.data_json)

    out = json.loads(spec.handler(ctx, {"entry": site.entry.slug, "url": vimeo, "field": "body"}))
    assert out["outcome"] == "staged" and out["field"] == "body" and out["provider"] == "Vimeo"
    entry = db_session.get(Entries, site.entry.id)
    db_session.refresh(entry)
    assert entry.data_json == before  # nothing live yet
    staged = entry.suggestion_json["data_json.body"]
    assert staged.endswith(f"\n\n{vimeo}\n") and vimeo in bare_urls(staged)
    assert entry.suggestion_json["_meta"]["operation"] == "add-embed"

    again = json.loads(spec.handler(ctx, {"entry": site.entry.slug, "url": vimeo, "field": "body"}))
    assert again["outcome"] == "already_present"
    # No field named: the embed field already holds another player, so it goes to the markdown body — where it already is.
    auto = json.loads(spec.handler(ctx, {"entry": site.entry.slug, "url": YT}))
    assert (auto["field"], auto["outcome"]) == ("body", "already_present")

    bad = json.loads(spec.handler(ctx, {"entry": site.entry.slug, "url": "https://example.com/x"}))
    assert "not a supported" in bad["error"]
    nohead = json.loads(
        spec.handler(ctx, {"entry": site.entry.slug, "url": "https://youtu.be/aaaaaaaaaaa", "field": "body", "after_heading": "Nope"})
    )
    assert "no heading" in nohead["error"]


def test_add_embed_goes_under_a_heading():
    from marvin.services.ai.tools.builtins_media import _insert_paragraph

    text, err = _insert_paragraph("# Title\nIntro\n\n## Listen\nSome words.\n", YT, "listen")
    assert err is None
    assert text == f"# Title\nIntro\n\n## Listen\n\n{YT}\n\nSome words.\n"
    assert bare_urls(text) == [YT]


def test_preview_embed_is_read_only():
    from marvin.services.ai.tools import get_tool
    from marvin.services.ai.tools.base import ToolContext
    from marvin.services.ai.tools.categories import category_of

    spec = get_tool("preview_embed")
    assert spec.read_only is True and category_of("preview_embed") == "entries_read" and category_of("add_embed") == "entries_author"
    assert "mcp" in spec.sources and "mcp" in get_tool("add_embed").sources
    out = json.loads(spec.handler(ToolContext(session=None, group_id=None), {"url": "https://example.com/x"}))
    assert out["supported"] is False and "YouTube" in out["providers"]
