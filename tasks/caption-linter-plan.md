# Caption linter, for every network that posts

Approved by Jared 2026-10-25 ("implement after phase 3"). Idea from `caption.py` in Jake Schincariol's
instagram-agent-skill (MIT): show what the feed shows before "… more", and check what fails there.

## The split (general in core, each network's "how" in its plugin)

- **Core** checks a caption the same way for every network: what is visible, where the hook is, an opening greeting or
  hashtag, a link where it won't work, too many hashtags, stock phrases.
- **Each plugin** declares its network's numbers once, on the provider (Integration SDK):

  ```python
  post_limits = {"max": 2200, "unit": "characters", "visible": 125, "hashtags_max": 30, "links": "not_clickable"}
  ```

  | network | max | unit | visible before "more" | hashtags_max | links |
  | --- | --- | --- | --- | --- | --- |
  | Instagram | 2200 | characters | 125 | 30 | not_clickable |
  | Facebook | 63206 | characters | 125 (mobile) | — | clickable |
  | Bluesky | 300 | graphemes | all | — | card |
  | Mastodon | 500 (the server may allow more) | characters | all | — | clickable |

  The numbers are what each plugin already enforces (`CAPTION_MAX`, `TEXT_MAX_GRAPHEMES`, `DEFAULT_MAX_CHARACTERS`).

## Steps

1. [ ] **SDK**: `IntegrationProvider.post_limits: ClassVar[dict] = {}` with the keys above documented; a release.
2. [ ] **Plugins**: Instagram, Facebook, Bluesky, Mastodon declare `post_limits`; a release each; Marvin's pins bumped.
3. [ ] **Core** `services/integrations/caption_check.py`: `check(text, link, limits) -> {network, visible, length, max,
       over, issues: [{code, message}]}`. Checks: over the limit; the visible window (the text up to `visible`, on a word
       boundary) and whether the first sentence fits it; opens with a greeting; opens with a hashtag or mention; a URL in
       the text where links aren't clickable (Instagram: "link in bio"); more hashtags than allowed; stock phrases (a short
       built-in list, the `slop.json` idea). Grapheme counting for Bluesky (the `regex` package's `\X`, as the plugin).
4. [ ] **API** `POST /api/groups/social-inbox/caption-check` `{text, link?, integrations?}` → one result per connected
       network that offers `social.post` (or the named ones). EDITOR. Pure: nothing is sent anywhere.
5. [ ] **Workflow editor**: on a `social.post` step, a **Check caption** panel under the text: one card per network with
       the visible window boxed and the issues; it re-checks as the text changes (debounced). A `${…}` template is checked
       as written, with a note that the real text comes at run time.
6. [ ] **Approvals**: when the step after an Approval is `social.post`, the approval card shows the same check for the
       text the run will post (interpolated from the run's context), so the person approving sees what the feed will show.
7. [ ] **Assistant**: a `check_caption` tool (EDITOR, read-only) so Ask and agents can lint before drafting a post step.
8. [ ] Tests (core checks per network, API, editor helper); docs (social.md, workflows.md); SDK regenerated.

Not doing: rewriting the caption (that's the improve-writing operation's job), or predicting reach.

## Review

Built 2026-10-25. SDK 0.19.0 (`post_limits`, `post_limits_of`, `check_post_limits`); Instagram 0.13.0, Facebook 0.6.0,
Bluesky 0.5.0, Mastodon 0.5.0 (Mastodon's stale version test now reads pyproject). Core `caption_check.py`, `POST
/caption-check`, `check_caption` tool, the editor panel (lib/captionCheck.ts), and the approval preview
(`approvals.post_preview`, using `engine.resumed_context`, extracted from `_resume_turn` so the preview interpolates exactly
as the resumed run will).

