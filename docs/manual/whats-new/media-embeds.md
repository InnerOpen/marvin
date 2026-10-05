# Media embeds

Paste a YouTube, Vimeo, Spotify, SoundCloud, Apple Music, Apple Podcasts, TIDAL, Simplecast or Transistor link, or Bandcamp's embed code, and the site shows a player.

## What it does

A supported media link becomes a player in two places:

- **In a markdown field**, when the link sits alone on its own line, with a blank line above and below (a heading directly above is fine too). The link stays in the text as you wrote it. A site that doesn't know about embeds yet keeps showing it as a link.
- **In an `embed` field**, a field type for a dedicated player slot, such as an episode's audio or a project's video.

These stay plain links:

- `<https://…>`;
- `[text](https://…)`;
- a link inside a sentence, list item, quote or code block;
- a link with punctuation straight after it;
- every link in a markdown field whose entry type sets **Auto-embed media links** off (`autoEmbed: false`).

Only allow-listed providers embed. Marvin builds every player itself from the link and never passes a provider's HTML on:

- the iframe `src` and its `allow`, `sandbox` and `referrerpolicy` attributes come from Marvin's provider registry;
- YouTube always plays from `youtube-nocookie.com`;
- Vimeo plays with `dnt=1`.

A look-alike host such as `youtube.com.example.org` or `notyoutube.com` is not a media link.

| Provider | Links | Player built from |
|---|---|---|
| YouTube | `watch?v=`, `youtu.be/`, `/shorts/`, `/embed/`, `/live/`, `playlist?list=` (`t=` becomes the start time) | the link |
| Vimeo | `vimeo.com/<id>`, unlisted `vimeo.com/<id>/<hash>`, `player.vimeo.com/video/<id>`, channel/group/album video links | the link |
| Spotify | track, album, playlist, artist, episode, show (`intl-xx/` allowed); `spotify.link` short links | the link; short links through Spotify's oEmbed |
| SoundCloud | `soundcloud.com/<user>/<track>`, `/sets/<set>`, private `s-…` links; `on.soundcloud.com` short links | the link; short links through oEmbed |
| Apple Music | album, playlist, song, music video; `?i=` picks a track | the link |
| Apple Podcasts | show and episode (`?i=`) | the link |
| TIDAL | track, album, playlist, video | the link |
| Simplecast | `<show>.simplecast.com/episodes/<slug>`, `player.simplecast.com/<id>` | episode pages through Simplecast's oEmbed |
| Transistor | `share.transistor.fm/s/<id>` | the link |
| Bandcamp | the embed code (Share / Embed on the album or track page) | the `EmbeddedPlayer` URL in the code; a plain Bandcamp page link shows as a link card, because Bandcamp has no oEmbed and the page link lacks the player id |

All oEmbed endpoints were checked with real requests on 5 October 2026. Apple Music (`music.apple.com/api/oembed`) and TIDAL (`oembed.tidal.com`) answer although oembed.com doesn't list them. Simplecast answers at `api.simplecast.com/oembed`; the endpoint oembed.com lists only redirects. Transistor's endpoint is `share.transistor.fm/oembed`, as its share pages advertise.

**Titles and thumbnails.** Marvin asks the provider's oEmbed for a link's title, author and thumbnail, and for the player id of links that don't carry one (Simplecast episodes, short links). It asks when you preview the link in the editor and when an entry using it is saved. The answer is kept in a cache shared by every workspace for 30 days, or 1 day after a failure. When the provider answers 401, 403 or 404, the link is `unavailable` and the site shows a link card. **The publishing API never calls a provider.** A link with nothing cached yet still publishes, as a player when the link is enough to build one and as a link card otherwise.

## Where

| What | Where |
|---|---|
| Embed button | The markdown editor's tab bar, next to **Write** and **Preview** (hidden when the field's auto-embed is off) |
| Embed field | Add a field of type **Media embed** to an entry type (Settings → **Manage Entry Types**), optionally limited to some providers |
| Auto-embed toggle | The markdown field's **Auto-embed media links** checkbox in the entry type's schema editor |
| Privacy mode | Settings → **Website Configuration** (`/publishing/site`) → **Embeds & Privacy** |
| Agent tools | `add_embed`, `preview_embed` |

## How to use

**Add a player to a body.** In the markdown editor, click **Embed**. Paste a link or the provider's embed code, then click **Check link** to see the provider, the title and the player. **Insert** puts the link into the text at the cursor as its own paragraph. You can also type or paste the link on its own line. **Preview** renders the markdown, sanitised, with players in place of embeddable links. The old regex preview let `javascript:` links through; this one strips them.

**A player slot.** Give the entry type a **Media embed** field. In the entry editor, paste a link or embed code into it. Pasted embed code is replaced by the link it points at, and the field previews the player. Limit a field to some providers with `providers` (for example `["youtube", "vimeo"]`). Saving another provider's link, or a link that isn't a media link, is refused with a message.

**Privacy.** **Embeds & Privacy** has two modes:

- **Click to load** (the default): the site shows a placeholder with the provider's name, the title, your consent text and a plain link. Nothing from the provider loads, so it sets no cookies, until the visitor clicks. No remote thumbnail is used.
- **Load players directly**: the site shows the player itself.

The consent text may contain `{provider}`, which is replaced with the provider's name. The default is "Loading this player connects to {provider}, which may set cookies."

**From an agent.**

- `add_embed(entry, url, field?, after_heading?)` adds a player to an existing entry. It needs EDITOR. The change is staged as the entry's pending suggestion, the same review wall a staged `revise_entry` uses, so nothing goes live until someone applies it on the entry page.
  - It picks an empty `embed` field that takes the provider; otherwise the first markdown field with auto-embed on. It never replaces another player unless you name the field.
  - In a markdown field the link goes in as its own paragraph, under `after_heading` when given, else at the end.
  - It is idempotent: a link already in the field, live or staged, comes back as `already_present`.
- `preview_embed(url)` says whether a link or embed code becomes a player, and its provider, kind, status, title and author. It needs AUTHOR and changes no entry.

Both tools are in the permission matrix (`entries_author` and `entries_read`) and are exposed over MCP. `compose_entry` and `revise_entry` are told how to place a player, and never to invent media links. An `embed` field in a compose takes a link only when the brief gives one.

## API

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/api/platform/media-embeds/providers` | any member | `{providers: [{key, name, kinds, hosts, examples, linkOnly, notes}], frameSources}`. In `hosts`, `*.domain` means any subdomain |
| POST | `/api/platform/media-embeds/resolve` | AUTHOR+ | body `{input, mode?}` (`mode` defaults to `direct` for the editor preview) → `{input, url, embed, error}`; `url` is the link to store (embed code is reduced to the provider link), `embed` a `PublishedEmbed`. An unsupported input answers 200 with `url: null` and an `error`. Limited to 60 resolves a minute per user (429) |

**Publishing API.** Every entry and entry list item carries `embeds`, keyed by the link exactly as written. `GET /site` carries `site.embeds` (`mode`, `consentText`, `frameSources`) beside `site.seo`. Each `PublishedEmbed` has:

- `provider`, `providerName` and `kind` (`video`, `audio`, `podcast` or `playlist`);
- `status` (`ok`, `link` or `unavailable`);
- `title`, `authorName` and `thumbnailUrl`;
- the structured `iframe` (`src`, `title`, `allow`, `sandbox`, `referrerpolicy`, plus `aspectRatio` or `height`);
- a `link` fallback;
- Marvin-built `html` in the site's mode.

The `html` shapes and the facade's data attributes are documented in [`docs/publishing-api.md`](https://github.com/InnerOpen/marvin/blob/develop/docs/publishing-api.md#media-embeds). MarvinAstro's `renderMarkdown(source, { embeds })` swaps such paragraphs for the `html`, and its loader turns a click-to-load facade into the player.

**Entry type schema.** A markdown field takes `autoEmbed: false` to keep its links plain. The new `embed` field is `{ "key": "video", "label": "Video", "type": "embed", "providers": ["youtube", "vimeo"] }`, and its value is the link.

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `MEDIA_EMBEDS_FETCH_ENABLED` | `true` | Ask providers' oEmbed for titles, thumbnails and player ids. When off, players are built from the link alone and links that need a lookup show as link cards. Lookups go through the same guarded client as integrations: public hosts only, re-checked on redirect, a 256 KB cap, a 5 s timeout and a `marvin-cms/embeds` User-Agent |

The cache table is `media_embed_cache` (migration `a78a8895a6a1`).

## Limits

- Bandcamp plays only from its embed code.
- An `<iframe>` typed by hand into markdown is not a Marvin embed and is not sanitised; that was already the case before this release.
- The site needs MarvinAstro's embed support (1.2.0) to show players; older sites keep showing links.
- A content-security policy can be built from `frameSources`, but no site emits one yet.
- Before this shipped, no published entry in production had a bare provider link on its own line, so no existing page changes on its next build.

## Related

- [Publishing API](publishing-api.md)
- [Agents and Ask](agents-and-ask.md)
