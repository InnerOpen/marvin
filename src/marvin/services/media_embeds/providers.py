"""The media-embed provider registry: which links become players, and how each player is built.

Every provider here is allow-listed. A link whose host is not in a provider's ``hosts`` is never
embedded, and every iframe ``src`` is rebuilt by Marvin from ids pulled out of the link (or, for the
few providers that keep the id only in their oEmbed reply, out of that reply's iframe ``src`` after
its host and path pass the provider's own check). Provider-supplied HTML is never stored or passed on.

Each provider declares:

- ``hosts`` — exact hostnames; ``*.example.com`` means any subdomain (never the bare domain).
- ``frame_hosts`` — the only hosts its iframes may load from (sites can build ``frame-src`` from them).
- ``oembed`` — the oEmbed endpoint (``{url}`` is the URL-encoded link), or None when there is none.
- ``parse`` — link → :class:`Target` (kind, canonical URL, iframe ``src`` when the link alone is enough).
- ``from_oembed_src`` — the oEmbed reply's iframe ``src`` → :class:`Target`, for links whose id only
  the provider knows (Simplecast episode pages, Spotify/SoundCloud short links).
- ``allow`` / ``sandbox`` and a fixed ``height`` (audio) or ``aspect_ratio`` (video) per target.

Endpoints checked with real requests on 2026-10-05 (fixtures in ``tests/fixtures/media_embeds``):
YouTube, Vimeo, Spotify, SoundCloud, Apple Podcasts, Apple Music (``music.apple.com/api/oembed``,
not listed on oembed.com), TIDAL (``oembed.tidal.com``), Simplecast (``api.simplecast.com/oembed`` —
the ``simplecast.com/oembed`` listed on oembed.com only redirects) and Transistor
(``share.transistor.fm/oembed``, advertised by its share pages). Bandcamp has no oEmbed and
bot-challenges server fetches: its player is built only from pasted embed code (the
``bandcamp.com/EmbeddedPlayer/...`` URL); a plain Bandcamp page link stays a link card.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlencode, urlsplit

KINDS = ("video", "audio", "podcast", "playlist")

VIDEO_ALLOW = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share; fullscreen"
AUDIO_ALLOW = "autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
DEFAULT_SANDBOX = "allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-presentation"
# Apple's own embed code asks for these (storage access for a signed-in listener, top navigation to open the app).
APPLE_SANDBOX = (
    "allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation allow-top-navigation-by-user-activation"
)
APPLE_ALLOW = "autoplay *; encrypted-media *; fullscreen *; clipboard-write"
TIDAL_SANDBOX = "allow-same-origin allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox"
TIDAL_ALLOW = "encrypted-media; fullscreen; clipboard-write https://embed.tidal.com; web-share"


@dataclass(frozen=True)
class Target:
    """What a link points at: its kind, its canonical public URL and (when known) the iframe src."""

    kind: str
    canonical_url: str
    src: str | None = None
    height: int | None = None
    aspect_ratio: str | None = None


@dataclass(frozen=True)
class Link:
    """A parsed, normalised http(s) link: lowercased host, path, query as a dict of first values."""

    raw: str
    scheme: str
    host: str
    path: str
    query: dict[str, str]
    fragment: str

    @property
    def segments(self) -> list[str]:
        return [s for s in self.path.split("/") if s]


@dataclass(frozen=True)
class EmbedProvider:
    key: str
    name: str
    hosts: tuple[str, ...]
    frame_hosts: tuple[str, ...]
    parse: Callable[[Link], Target | None]
    oembed: str | None = None
    from_oembed_src: Callable[[Link], Target | None] | None = None
    allow_video: str = VIDEO_ALLOW
    allow_audio: str = AUDIO_ALLOW
    sandbox: str = DEFAULT_SANDBOX
    kinds: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    link_only: bool = False
    """True when a plain link never becomes a player (only pasted embed code does)."""
    notes: str = ""

    def allow_for(self, kind: str) -> str:
        return self.allow_video if kind == "video" else self.allow_audio

    def owns_host(self, host: str) -> bool:
        return host_matches(host, self.hosts)

    def frame_host_ok(self, src: str | None) -> bool:
        """True when ``src`` is an https URL on one of this provider's frame hosts."""
        if not src:
            return False
        parts = urlsplit(src)
        return parts.scheme == "https" and (parts.hostname or "") in self.frame_hosts and not parts.username and not parts.password


def host_matches(host: str, patterns: tuple[str, ...] | list[str]) -> bool:
    """Exact host match, or ``*.domain`` = a real subdomain of ``domain`` (never a look-alike)."""
    host = (host or "").lower().rstrip(".")
    for pat in patterns:
        if pat.startswith("*."):
            if host.endswith("." + pat[2:]) and len(host) > len(pat) - 1:
                return True
        elif host == pat:
            return True
    return False


# ---------------------------------------------------------------------------------------------------
# YouTube — always played from youtube-nocookie.com.

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_LIST = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
_YT_T = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$")


def _yt_seconds(value: str | None) -> int | None:
    if not value:
        return None
    m = _YT_T.match(value.strip())
    if not m or not any(m.groups()):
        return None
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    total = h * 3600 + mi * 60 + s
    return total or None


def _youtube_target(video_id: str, *, start: int | None = None, shorts: bool = False) -> Target:
    canonical = f"https://www.youtube.com/watch?v={video_id}" + (f"&t={start}s" if start else "")
    if shorts:
        canonical = f"https://www.youtube.com/shorts/{video_id}"
    src = f"https://www.youtube-nocookie.com/embed/{video_id}" + (f"?start={start}" if start else "")
    return Target(kind="video", canonical_url=canonical, src=src, aspect_ratio="9/16" if shorts else "16/9")


def _parse_youtube(link: Link) -> Target | None:
    segs = link.segments
    start = _yt_seconds(link.query.get("t") or link.query.get("start"))
    if link.host == "youtu.be":
        if len(segs) == 1 and _YT_ID.match(segs[0]):
            return _youtube_target(segs[0], start=start)
        return None
    if segs == ["watch"] and _YT_ID.match(link.query.get("v", "")):
        return _youtube_target(link.query["v"], start=start)
    if segs == ["playlist"] and _YT_LIST.match(link.query.get("list", "")):
        lst = link.query["list"]
        return Target(
            kind="playlist",
            canonical_url=f"https://www.youtube.com/playlist?list={lst}",
            src=f"https://www.youtube-nocookie.com/embed/videoseries?list={lst}",
            aspect_ratio="16/9",
        )
    if segs == ["embed", "videoseries"]:  # 11 characters, so test it before the video-id forms
        if _YT_LIST.match(link.query.get("list", "")):
            return _parse_youtube(Link(link.raw, "https", "www.youtube.com", "/playlist", {"list": link.query["list"]}, ""))
        return None
    if len(segs) == 2 and segs[0] in ("embed", "shorts", "live", "v") and _YT_ID.match(segs[1]):
        return _youtube_target(segs[1], start=start, shorts=segs[0] == "shorts")
    return None


# ---------------------------------------------------------------------------------------------------
# Vimeo — dnt=1 (no tracking cookies); unlisted videos carry a privacy hash.

_DIGITS = re.compile(r"^\d{1,12}$")
_HEX = re.compile(r"^[0-9a-f]{6,20}$")


def _vimeo_target(video_id: str, privacy_hash: str | None) -> Target:
    canonical = f"https://vimeo.com/{video_id}" + (f"/{privacy_hash}" if privacy_hash else "")
    src = f"https://player.vimeo.com/video/{video_id}?dnt=1" + (f"&h={privacy_hash}" if privacy_hash else "")
    return Target(kind="video", canonical_url=canonical, src=src, aspect_ratio="16/9")


def _parse_vimeo(link: Link) -> Target | None:
    segs = link.segments
    if link.host == "player.vimeo.com":
        if len(segs) == 2 and segs[0] == "video" and _DIGITS.match(segs[1]):
            h = link.query.get("h")
            return _vimeo_target(segs[1], h if h and _HEX.match(h) else None)
        return None
    if len(segs) in (1, 2) and _DIGITS.match(segs[0]):
        h = segs[1] if len(segs) == 2 else None
        if h is not None and not _HEX.match(h):
            return None
        return _vimeo_target(segs[0], h)
    # vimeo.com/channels/<name>/<id>, /groups/<name>/videos/<id>, /album/<n>/video/<id>
    if len(segs) == 3 and segs[0] == "channels" and _DIGITS.match(segs[2]):
        return _vimeo_target(segs[2], None)
    if len(segs) == 4 and segs[0] in ("groups", "album") and segs[2] in ("videos", "video") and _DIGITS.match(segs[3]):
        return _vimeo_target(segs[3], None)
    return None


# ---------------------------------------------------------------------------------------------------
# Spotify

_SPOTIFY_ID = re.compile(r"^[A-Za-z0-9]{22}$")
_SPOTIFY_KIND = {"track": "audio", "album": "playlist", "playlist": "playlist", "artist": "playlist", "episode": "podcast", "show": "podcast"}
_SPOTIFY_HEIGHT = {"track": 152, "episode": 152}


def _spotify_target(kind_seg: str, item_id: str) -> Target:
    return Target(
        kind=_SPOTIFY_KIND[kind_seg],
        canonical_url=f"https://open.spotify.com/{kind_seg}/{item_id}",
        src=f"https://open.spotify.com/embed/{kind_seg}/{item_id}",
        height=_SPOTIFY_HEIGHT.get(kind_seg, 352),
    )


def _parse_spotify(link: Link) -> Target | None:
    if link.host == "spotify.link":
        # A short link: only Spotify's oEmbed knows what it points at.
        segs = link.segments
        return Target(kind="audio", canonical_url=f"https://spotify.link/{segs[0]}") if len(segs) == 1 else None
    segs = link.segments
    if segs and segs[0].startswith("intl-"):
        segs = segs[1:]
    if segs and segs[0] == "embed":
        segs = segs[1:]
    if len(segs) == 2 and segs[0] in _SPOTIFY_KIND and _SPOTIFY_ID.match(segs[1]):
        return _spotify_target(segs[0], segs[1])
    return None


def _spotify_from_src(link: Link) -> Target | None:
    return _parse_spotify(link) if link.host == "open.spotify.com" else None


# ---------------------------------------------------------------------------------------------------
# SoundCloud — the widget takes the public track/set URL, so no id lookup is needed.

_SC_SLUG = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_SC_RESERVED = {
    "discover",
    "search",
    "stream",
    "you",
    "upload",
    "settings",
    "pages",
    "charts",
    "messages",
    "notifications",
    "people",
    "tags",
    "terms-of-use",
    "jobs",
    "mobile",
    "signin",
    "logout",
}


def _soundcloud_widget(public_url: str, kind: str) -> Target:
    return Target(
        kind=kind,
        canonical_url=public_url,
        src="https://w.soundcloud.com/player/?" + urlencode({"url": public_url}, quote_via=quote),
        height=166 if kind == "audio" else 450,
    )


def _parse_soundcloud(link: Link) -> Target | None:
    segs = link.segments
    if link.host == "on.soundcloud.com":
        return Target(kind="audio", canonical_url=f"https://on.soundcloud.com/{segs[0]}") if len(segs) == 1 else None
    if link.host == "w.soundcloud.com":
        return _soundcloud_from_src(link)
    if len(segs) < 2 or segs[0].lower() in _SC_RESERVED or not all(_SC_SLUG.match(s) for s in segs):
        return None
    if len(segs) in (3, 4) and segs[1] == "sets":
        # /<user>/sets/<set>[/s-<secret>]
        if len(segs) == 4 and not segs[3].startswith("s-"):
            return None
        return _soundcloud_widget("https://soundcloud.com/" + "/".join(segs), "playlist")
    if len(segs) == 2 or (len(segs) == 3 and segs[2].startswith("s-")):
        # /<user>/<track>[/s-<secret>]
        if segs[1] in ("sets", "tracks", "likes", "reposts", "albums", "popular-tracks", "followers", "following", "comments"):
            return None
        return _soundcloud_widget("https://soundcloud.com/" + "/".join(segs), "audio")
    return None


_SC_API_PATH = re.compile(r"^/(tracks|playlists)/(\d{1,15})$")


def _soundcloud_from_src(link: Link) -> Target | None:
    """``w.soundcloud.com/player/?url=https://api.soundcloud.com/tracks/123`` (oEmbed html / embed code)."""
    if link.host != "w.soundcloud.com" or link.path.rstrip("/") != "/player":
        return None
    inner_url = link.query.get("url", "")
    inner = urlsplit(inner_url)
    if inner.hostname in ("soundcloud.com", "www.soundcloud.com"):  # the widget also takes a public URL
        public = make_link(inner_url)
        return _parse_soundcloud(public) if public else None
    if inner.scheme not in ("https", "http") or inner.hostname != "api.soundcloud.com":
        return None
    m = _SC_API_PATH.match(inner.path)
    if not m:
        return None
    api_url = f"https://api.soundcloud.com/{m.group(1)}/{m.group(2)}"
    kind = "audio" if m.group(1) == "tracks" else "playlist"
    target = _soundcloud_widget(api_url, kind)
    return Target(kind=kind, canonical_url=target.src or api_url, src=target.src, height=target.height)


# ---------------------------------------------------------------------------------------------------
# Apple Music / Apple Podcasts — the embed host mirrors the public path.

_APPLE_CC = re.compile(r"^[a-z]{2}$")
_APPLE_SLUG = re.compile(r"^[^/?#]{1,200}$")
_APPLE_ID = re.compile(r"^(?:id)?\d{1,15}$")
_APPLE_ITEM = re.compile(r"^(?:pl\.)?[A-Za-z0-9.-]{1,64}$")


def _apple_query(link: Link) -> str:
    i = link.query.get("i")
    return f"?i={i}" if i and _DIGITS.match(i) else ""


def _parse_apple_music(link: Link) -> Target | None:
    segs = link.segments
    if len(segs) not in (3, 4) or not _APPLE_CC.match(segs[0]):
        return None
    kind_seg = segs[1]
    if kind_seg not in ("album", "playlist", "song", "music-video"):
        return None
    item = segs[-1]
    if not (_APPLE_ID.match(item) or (kind_seg == "playlist" and _APPLE_ITEM.match(item))):
        return None
    if len(segs) == 4 and not _APPLE_SLUG.match(segs[2]):
        return None
    path = "/" + "/".join(quote(s, safe="-._~%") for s in segs)
    q = _apple_query(link)
    if kind_seg == "music-video":
        kind, height, aspect = "video", None, "16/9"
    elif kind_seg == "song" or q:
        kind, height, aspect = "audio", 175, None
    else:
        kind, height, aspect = "playlist", 450, None
    return Target(
        kind=kind,
        canonical_url=f"https://music.apple.com{path}{q}",
        src=f"https://embed.music.apple.com{path}{q}",
        height=height,
        aspect_ratio=aspect,
    )


def _parse_apple_podcasts(link: Link) -> Target | None:
    segs = link.segments
    if len(segs) == 3 and segs[0] == "podcast":
        segs = ["us", *segs]  # podcasts.apple.com/podcast/<slug>/id… (no storefront) — Apple defaults to us
    if len(segs) != 4 or not _APPLE_CC.match(segs[0]) or segs[1] != "podcast" or not segs[3].startswith("id"):
        return None
    if not _APPLE_ID.match(segs[3]) or not _APPLE_SLUG.match(segs[2]):
        return None
    path = "/" + "/".join(quote(s, safe="-._~%") for s in segs)
    q = _apple_query(link)
    return Target(
        kind="podcast",
        canonical_url=f"https://podcasts.apple.com{path}{q}",
        src=f"https://embed.podcasts.apple.com{path}{q}",
        height=175 if q else 450,
    )


# ---------------------------------------------------------------------------------------------------
# TIDAL

_TIDAL_TYPES = {"track": "tracks", "album": "albums", "playlist": "playlists", "video": "videos"}
_TIDAL_ID = re.compile(r"^(?:\d{1,15}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")


def _tidal_target(kind_seg: str, item_id: str) -> Target:
    kind = {"track": "audio", "video": "video"}.get(kind_seg, "playlist")
    return Target(
        kind=kind,
        canonical_url=f"https://tidal.com/browse/{kind_seg}/{item_id}",
        src=f"https://embed.tidal.com/{_TIDAL_TYPES[kind_seg]}/{item_id}",
        height=None if kind == "video" else (120 if kind == "audio" else 400),
        aspect_ratio="16/9" if kind == "video" else None,
    )


def _parse_tidal(link: Link) -> Target | None:
    segs = link.segments
    if link.host == "embed.tidal.com":
        rev = {v: k for k, v in _TIDAL_TYPES.items()}
        if len(segs) == 2 and segs[0] in rev and _TIDAL_ID.match(segs[1]):
            return _tidal_target(rev[segs[0]], segs[1])
        return None
    if segs and segs[0] == "browse":
        segs = segs[1:]
    if len(segs) == 2 and segs[0] in _TIDAL_TYPES and _TIDAL_ID.match(segs[1]):
        return _tidal_target(segs[0], segs[1])
    return None


# ---------------------------------------------------------------------------------------------------
# Bandcamp — no oEmbed; players only from the EmbeddedPlayer URL in pasted embed code.

_BC_ITEM = re.compile(r"^(album|track)=(\d{1,15})$")


def _parse_bandcamp(link: Link) -> Target | None:
    segs = link.segments
    if link.host == "bandcamp.com" and segs and segs[0] == "EmbeddedPlayer":
        for seg in segs[1:]:
            m = _BC_ITEM.match(seg)
            if m:
                kind_seg, item_id = m.groups()
                return Target(
                    kind="audio" if kind_seg == "track" else "playlist",
                    canonical_url=f"https://bandcamp.com/EmbeddedPlayer/{kind_seg}={item_id}",
                    src=(
                        f"https://bandcamp.com/EmbeddedPlayer/{kind_seg}={item_id}"
                        "/size=large/bgcol=ffffff/linkcol=0687f5/tracklist=false/artwork=small/transparent=true/"
                    ),
                    height=120,
                )
        return None
    if link.host.endswith(".bandcamp.com") and len(segs) == 2 and segs[0] in ("album", "track"):
        # A page link: the player needs a numeric id only Bandcamp's embed code carries → link card.
        return Target(kind="audio" if segs[0] == "track" else "playlist", canonical_url=f"https://{link.host}/{segs[0]}/{segs[1]}")
    return None


# ---------------------------------------------------------------------------------------------------
# Simplecast — the episode id is only in the oEmbed reply (player.simplecast.com/<uuid>).

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SIMPLECAST_NON_SHOW = {"api", "feeds", "cdn", "image", "www", "dashboard", "app", "help", "player"}


def _simplecast_player(uuid: str) -> Target:
    url = f"https://player.simplecast.com/{uuid}"
    return Target(kind="podcast", canonical_url=url, src=url, height=200)


def _parse_simplecast(link: Link) -> Target | None:
    segs = link.segments
    if link.host == "player.simplecast.com":
        return _simplecast_player(segs[0]) if len(segs) == 1 and _UUID.match(segs[0]) else None
    sub = link.host.split(".", 1)[0]
    if sub in _SIMPLECAST_NON_SHOW:
        return None
    if len(segs) == 2 and segs[0] == "episodes" and re.match(r"^[a-z0-9-]{1,200}$", segs[1]):
        return Target(kind="podcast", canonical_url=f"https://{link.host}/episodes/{segs[1]}")
    return None


def _simplecast_from_src(link: Link) -> Target | None:
    return _parse_simplecast(link) if link.host == "player.simplecast.com" else None


# ---------------------------------------------------------------------------------------------------
# Transistor — share.transistor.fm/s/<id> (page) ↔ /e/<id> (player).

_TRANSISTOR_ID = re.compile(r"^[a-z0-9]{6,16}$")


def _parse_transistor(link: Link) -> Target | None:
    segs = link.segments
    if len(segs) == 2 and segs[0] in ("s", "e") and _TRANSISTOR_ID.match(segs[1]):
        return Target(
            kind="podcast",
            canonical_url=f"https://share.transistor.fm/s/{segs[1]}",
            src=f"https://share.transistor.fm/e/{segs[1]}",
            height=180,
        )
    return None


# ---------------------------------------------------------------------------------------------------

PROVIDERS: dict[str, EmbedProvider] = {
    p.key: p
    for p in (
        EmbedProvider(
            key="youtube",
            name="YouTube",
            hosts=("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com"),
            frame_hosts=("www.youtube-nocookie.com",),
            parse=_parse_youtube,
            oembed="https://www.youtube.com/oembed?format=json&url={url}",
            kinds=("video", "playlist"),
            examples=("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"),
        ),
        EmbedProvider(
            key="vimeo",
            name="Vimeo",
            hosts=("vimeo.com", "www.vimeo.com", "player.vimeo.com"),
            frame_hosts=("player.vimeo.com",),
            parse=_parse_vimeo,
            oembed="https://vimeo.com/api/oembed.json?url={url}",
            kinds=("video",),
            examples=("https://vimeo.com/1084537",),
        ),
        EmbedProvider(
            key="spotify",
            name="Spotify",
            hosts=("open.spotify.com", "spotify.link"),
            frame_hosts=("open.spotify.com",),
            parse=_parse_spotify,
            from_oembed_src=_spotify_from_src,
            oembed="https://open.spotify.com/oembed?url={url}",
            kinds=("audio", "playlist", "podcast"),
            examples=("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",),
        ),
        EmbedProvider(
            key="soundcloud",
            name="SoundCloud",
            hosts=("soundcloud.com", "www.soundcloud.com", "m.soundcloud.com", "on.soundcloud.com", "w.soundcloud.com"),
            frame_hosts=("w.soundcloud.com",),
            parse=_parse_soundcloud,
            from_oembed_src=_soundcloud_from_src,
            oembed="https://soundcloud.com/oembed?format=json&url={url}",
            kinds=("audio", "playlist"),
            examples=("https://soundcloud.com/forss/flickermood",),
        ),
        EmbedProvider(
            key="apple_music",
            name="Apple Music",
            hosts=("music.apple.com", "embed.music.apple.com"),
            frame_hosts=("embed.music.apple.com",),
            parse=_parse_apple_music,
            oembed="https://music.apple.com/api/oembed?url={url}",
            allow_video=APPLE_ALLOW,
            allow_audio=APPLE_ALLOW,
            sandbox=APPLE_SANDBOX,
            kinds=("audio", "playlist", "video"),
            examples=("https://music.apple.com/us/album/1989-taylors-version/1708308989",),
        ),
        EmbedProvider(
            key="apple_podcasts",
            name="Apple Podcasts",
            hosts=("podcasts.apple.com", "embed.podcasts.apple.com"),
            frame_hosts=("embed.podcasts.apple.com",),
            parse=_parse_apple_podcasts,
            oembed="https://podcasts.apple.com/api/oembed?url={url}",
            allow_video=APPLE_ALLOW,
            allow_audio=APPLE_ALLOW,
            sandbox=APPLE_SANDBOX,
            kinds=("podcast",),
            examples=("https://podcasts.apple.com/us/podcast/the-daily/id1200361736",),
        ),
        EmbedProvider(
            key="tidal",
            name="TIDAL",
            hosts=("tidal.com", "www.tidal.com", "listen.tidal.com", "embed.tidal.com"),
            frame_hosts=("embed.tidal.com",),
            parse=_parse_tidal,
            oembed="https://oembed.tidal.com/?url={url}",
            allow_video=TIDAL_ALLOW,
            allow_audio=TIDAL_ALLOW,
            sandbox=TIDAL_SANDBOX,
            kinds=("audio", "playlist", "video"),
            examples=("https://tidal.com/browse/track/77646168",),
        ),
        EmbedProvider(
            key="bandcamp",
            name="Bandcamp",
            hosts=("bandcamp.com", "*.bandcamp.com"),
            frame_hosts=("bandcamp.com",),
            parse=_parse_bandcamp,
            kinds=("audio", "playlist"),
            examples=("https://bandcamp.com/EmbeddedPlayer/album=1234567890",),
            link_only=True,
            notes="Paste Bandcamp's embed code (Share/Embed on the album or track page); a plain page link shows as a link.",
        ),
        EmbedProvider(
            key="simplecast",
            name="Simplecast",
            hosts=("*.simplecast.com",),
            frame_hosts=("player.simplecast.com",),
            parse=_parse_simplecast,
            from_oembed_src=_simplecast_from_src,
            oembed="https://api.simplecast.com/oembed?url={url}",
            kinds=("podcast",),
            examples=("https://uibreakfast.simplecast.com/episodes/better-done-than-perfect-marketing-channels-programs-with-asia-orangio",),
        ),
        EmbedProvider(
            key="transistor",
            name="Transistor",
            hosts=("share.transistor.fm",),
            frame_hosts=("share.transistor.fm",),
            parse=_parse_transistor,
            oembed="https://share.transistor.fm/oembed?url={url}",
            kinds=("podcast",),
            examples=("https://share.transistor.fm/s/9c22a01c",),
        ),
    )
}


def get_provider(key: str) -> EmbedProvider | None:
    return PROVIDERS.get(key)


def frame_sources() -> list[str]:
    """Every origin a Marvin-built player may load from, for a site's ``frame-src``."""
    return sorted({f"https://{h}" for p in PROVIDERS.values() for h in p.frame_hosts})


def make_link(url: str) -> Link | None:
    """Parse an http(s) URL into a :class:`Link`; None for anything that isn't a plain public web URL
    (other schemes, credentials in the authority, non-default ports, whitespace or angle brackets)."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url or len(url) > 2048 or any(c.isspace() or c in '<>"\\' for c in url):
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return None
    if port not in (None, 80, 443):
        return None
    query = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=False).items() if v}
    return Link(
        raw=url, scheme=parts.scheme.lower(), host=parts.hostname.lower().rstrip("."), path=parts.path or "/", query=query, fragment=parts.fragment
    )
