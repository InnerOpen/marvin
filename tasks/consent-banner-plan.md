# Plan: cookie-consent banner + privacy/cookie policy rendering (2026-10-19)

Jared (2026-10-19): a cookie-consent banner and privacy/cookie policy rendering for his sites, driven by Marvin's
existing `site.privacy` data. Drafted from the code (read-only); nothing built yet. **Not legal advice** — rules vary by
jurisdiction (ePrivacy/GDPR, Spanish AEPD reading, CNIL, UK PECR, US state laws); Jared decides policy text and calls.

## 0. Model (proposed)
- **Facts in Marvin, prose in an entry, MarvinAstro renders both** (the split already proposed in the Brain note
  "Marvin Privacy and Cookie Settings").
- **No banner unless needed:** shown only when `bannerRequired` (≥1 listed cookie/storage entry not `necessary`); an
  all-necessary/cookieless site ships zero banner bytes.
- **Fail closed:** non-necessary scripts ship inert (`type="text/plain"`), activated only by the consent runtime; no JS →
  nothing optional loads and the banner stays hidden.
- **Choice bound to a consent version:** hash of the non-necessary cookie set (`category|name|provider`); changed set or
  expired choice → ask again, nothing optional loads until answered.

## 1. Findings
| # | Where | Today |
|---|---|---|
| 1 | `src/marvin/schemas/publishing.py:650-724` | `CookieCategory`, `PrivacyController/Processor/Cookie/Consent`, `SitePrivacy`; `banner_required` derived :720-724; docstring :711-712 "does not run a consent banner" |
| 2 | `schemas/group/preferences.py:141-150` | validates the privacy block on save (422); `services/publish_site.py:64-73,103` ignores a malformed stored block |
| 3 | `frontend/src/pages/publishing/site.astro:415-466` | admin form; copy :417 "Marvin does not show a consent banner"; live "banner required" readout :449-452, :755-759 |
| 4 | `routes/groups/preferences_controller.py:196-216` | each save emits `workspace_settings_changed` — already dates every cookie-list change |
| 5 | `MarvinAstro/src/site.ts:131-132`, `src/types.ts:85-114` | `ApiSite` has `embeds` (read tolerantly from untyped config), no `privacy` |
| 6 | `MarvinAstro/src/components/embed-frame.ts:123-168`, `EmbedLoader.astro` | click-to-load facades (`FACADE_SELECTOR`, `activateEmbedFacade`); same markup in Marvin's published markdown HTML; the zero-import runtime pattern to copy |
| 7 | `MarvinAstro/package.json` | local 1.4.0 vs HEAD `32c796a` (npm 2.0.0) — pull first; peer `@inneropen/marvin-sdk ^3‖^4` lags SDK 7.2 (which types `SitePrivacy`) → privacy read must be tolerant, no SDK bump needed; `.releaserc` publishes develop as `next` prereleases |
| 8 | `MarvinAstro/src/chrome.ts:258-266` | `role: 'legal'` footer links → `legalLinks` |
| 9 | all three sites | none read `site.privacy`; no Playwright in any repo; MarvinAstro has vitest + jsdom + Astro Container API (`tests/components/`) |

## 2. What each site actually sets today
| Site | Third parties / storage | Banner needed? |
|---|---|---|
| GraceMartinFranklin (develop) | **Google Fonts from googleapis/gstatic** (`src/layouts/BaseLayout.astro:32-37`) — IP to Google (LG München I 3 O 17493/20, 2022: unlawful without consent); Square checkout is an outbound link (`works/[slug].astro:60-83`) → Square cookies on Square's domain; forms/newsletter via Pages Functions to Marvin (`functions/api/forms/[slug].js`, `Newsletter.astro:30`); embeds click-to-load; no analytics; no privacy page; footer doesn't render `legalLinks` (`Footer.astro`, `lib/content.ts:37`) | No, once fonts are self-hosted |
| mashandburnco (develop) | self-hosted fonts (`public/fonts`); `localStorage['mb-theme']` (`BaseLayout.astro:38-45`, `ThemeToggle.astro:29`); embeds click-to-load; privacy entry at `/workshop-reference/privacy` (`lib/content.ts:26-28`); footer renders legal links (`Footer.astro:21,76`); holding build `holding/pages/privacy.astro:40-42` says "no analytics" | No |
| inneropen (develop = full site; main = coming-soon + `/privacy`, `4b69280`) | Fontsource (`BaseLayout.astro:2-6`); `localStorage['inneropen-theme']` (`:40-44`); legal links into footer (`Footer.astro:9`) | No |
| all | Cloudflare proxy/Pages: `__cf_bm`/`cf_clearance` only if bot/challenge features on (Bot Fight Mode off per Brain); Pages Web Analytics injection is a dashboard setting (cookieless) — check | No |

Theme `localStorage` is a user-requested setting → consent-exempt (WP29 Opinion 04/2012 "user-interface customisation")
— list as `necessary`. **Self-hosted Umami** (cookieless): CNIL-style audience-measurement exemption (first-party,
aggregate, no cross-site) → disclosure, not a banner; EDPB Guidelines 2/2023 read Art. 5(3) wider — conservative option:
list as `analytics` and gate (turns the banner on). Default recommended: ungated, disclosed as a processor.

**Bottom line: none of the three sites needs a banner today.** The policy components are useful immediately; the banner
ships ready and renders nothing until a non-necessary entry appears.

## 3. Stage 1 — MarvinAstro: privacy data + policy components (2.1.0)
- `src/privacy.ts`: `sitePrivacy(raw)` tolerant normalizer (modelled on `siteEmbeds`; computes `bannerRequired` locally
  if absent); `consentVersion(privacy)` = FNV-1a hex over sorted `category|name|provider` of non-necessary cookies (+
  `consent.version` once Stage 3 adds it) — rewording a purpose or `lastReviewed` does not re-prompt. Wire
  `ApiSite.privacy?` (`types.ts`), filled at `site.ts:~131` from `config.privacy ?? metadata.privacy`.
- Components (server-rendered, zero JS, exported from `index.ts`): `<CookieTable cookies category? includeConsentEntry=true>`
  (grouped by category; adds the `marvin-consent` storage row as necessary when the banner is required and it isn't
  listed); `<ProcessorTable processors>` (region, transfer basis, DPA/privacy links via `safeLinkHref`);
  `<PrivacyPolicy privacy headingLevel=2>` (controller block, processors, cookies, "Last reviewed"; default slot for the
  entry's prose).
- `privacy.css`: low-specificity `:where()` + `--marvin-privacy-*`; tables stack below 600px. README section.

## 4. Stage 2 — MarvinAstro: consent runtime + banner (2.2.0)
- `src/components/consent.ts` (zero imports, <3 KB gz, `embed-frame.ts` pattern): record
  `localStorage['marvin-consent'] = {v:1, version, choices:{preferences,analytics,marketing}, at}`; expiry default 6
  months (`maxAgeDays`); refusals stored too. Gating: `<script type="text/plain" data-consent="analytics" data-src="…">`
  → real script (attributes copied); `<template data-consent="marketing">` cloned in; multiple categories = all required.
  API `window.marvinConsent = { get(), has(cat), set(choices), open() }`; `marvin:consent` CustomEvent on `document`
  `{choices, version, initial}` on load (valid choice) and on change. Withdrawal: expire listed first-party cookies of
  revoked categories (trailing-wildcard `_ga*`, host + parent domain), then reload.
- `<ConsentBanner privacy policyHref labels? maxAgeDays? embeds?>`: renders nothing unless `bannerRequired`; first in
  `<body>`; markup `hidden`, revealed by the runtime (no dead banner without JS); non-modal bottom bar
  (`<section aria-labelledby>`), no focus stealing; **Accept all** and **Reject all** same class/size, **Customise**
  beside; no "X", nothing pre-ticked. Customise = native `<dialog>` (`showModal()` focus trap, Esc cancels): necessary
  (ticked, disabled) + only categories present in `site.privacy.cookies`, each with description + cookie names, unticked;
  **Save choices**. Focus returns to the opener; after a banner choice → `main`. ≥4.5:1 contrast,
  `prefers-reduced-motion`; at 390px buttons stack full-width, bar ≤40vh, scrolls.
- `<CookieSettingsLink>`: real `<a href={cookiePolicyHref}>`; with JS opens the dialog (`data-marvin-consent-open`),
  without JS goes to the policy page; `<CookieTable>` adds a `<noscript>` "Optional cookies are off because JavaScript
  is disabled."
- Embeds stay click-to-load per item and don't affect `bannerRequired` (the click is the consent); opt-in
  `embeds="marketing"` auto-activates facades via `activateEmbedFacade` after that consent — off by default (Q3).
- `consent.css`: `--marvin-consent-{bg,fg,accent,radius,font,shadow,z}`.

## 5. Stage 3 — Marvin: banner copy + re-consent bump (optional, minimal)
- `PrivacyConsent` (`publishing.py:698-703`) + `version: str | None` (manual re-prompt bump) and
  `banner: PrivacyBannerText | None` = `{title, body, acceptAll, rejectAll, customise, save, settingsLink,
  categories:{preferences,analytics,marketing}}` — nulls fall back to MarvinAstro defaults. Update docstring :707-713;
  `site.astro` :417 copy ("sites using MarvinAstro show a banner when the readout says yes"); collapsed "Banner text
  (optional)" group near :449-466 (`collectPrivacy` :761-775). Tests in `tests/test_site_privacy.py`; docs
  (`whats-new/publishing-api.md`, OpenAPI); SDK regen (coordinator).
- **No consent-logging endpoint** (Q4). If ever wanted: `POST /api/publish/{ws}/consent` via the site's Pages Function,
  storing choice + policy version + day only — no IP, no UA.

## 6. Stage 4 — site rollouts
- **mashandburnco:** Marvin facts (controller; processors Cloudflare (DPF+SCCs) + Marvin host; cookie `mb-theme`
  necessary); render `<PrivacyPolicy>` under the entry on `/workshop-reference/privacy` (`SiteWorkshopReferencePage`);
  set `consent.policyEntrySlug`; `<ConsentBanner>` + `<CookieSettingsLink>` in layout/footer (render nothing today).
- **GraceMartinFranklin:** self-host DM Sans + Playfair Display via `@fontsource` (else list Google as a processor);
  `/privacy` = entry + `<PrivacyPolicy>` (processors: Square (orders), Cloudflare, Marvin, newsletter provider); render
  `legalLinks` in `Footer.astro` and add privacy to the static fallback (`content.ts:37`).
- **inneropen:** develop `/privacy` from entry + `<PrivacyPolicy>`, list `inneropen-theme`, banner/link slots; main keeps
  its hand-written `/privacy` until develop's full site ships.
- **Umami:** Q8 ungated → processor row; gated → `analytics` row + `<script type="text/plain" data-consent="analytics" data-src=…>`.

## 7. Testing
- MarvinAstro vitest/jsdom (`tests/components/consent.test.ts`, `privacy.test.ts`): normalizer tolerance +
  `bannerRequired` fallback; `consentVersion` stable across order/wording, changes on category/name; runtime (no record →
  nothing activates; accept/reject/partial; expiry; version mismatch re-asks with scripts inert; `data-src`/`<template>`
  activation copies attributes, runs once; event detail; withdrawal deletes cookies incl. wildcards then reloads
  (stubbed)); Container API (empty when not required; `hidden` markup; equal button classes; no pre-ticked boxes;
  escaped provider text).
- Playwright via `npx` from a scratch dir against `astro preview` (not a repo dependency), desktop + 390px: first visit
  banner + gated request absent; Reject → reload → no banner/no request; Accept → request; settings link reopens dialog;
  bumped version re-asks; JS off → no banner/no request, link → policy page; keyboard Tab/Esc/focus return; axe-core 0
  serious; screenshots. A dev workspace on api-dev with a dummy `analytics` row + gated test script.

## 8. Rollout, verification, rollback
1. MarvinAstro Stage 1 → develop (`2.1.0-next.N`) → one site's develop preview → main `2.1.0`; Stage 2 likewise `2.2.0`
   (minor, additive).
2. Sites: develop (Cloudflare preview) → check the policy page vs Marvin facts, confirm no banner → main.
3. Marvin Stage 3: dev → prod (MarvinAstro reads new fields tolerantly; order free).
Rollback: pin the site's MarvinAstro or remove `<ConsentBanner>`; gated scripts stay inert (fails closed).

## 9. Risks
- Legal specifics vary: defaults follow the strict EU reading; Jared owns text + classification (recheck before the
  Spain move makes him an EU-resident controller).
- Silent non-loading: a gated script on a site with `bannerRequired=false` never runs — document; dev build warns when
  `data-consent` exists but no banner renders.
- Safari ITP caps script-written storage at 7 days without interaction (re-asks sooner; cookie or localStorage alike).
- CSP: inline gated scripts need a hash/`unsafe-inline` — prefer `data-src` (no site sets a CSP today).
- Drift: a cookie set in code but missing from Marvin's list → policy page + rollout checklist + DevTools review.
- `marvin-consent` must be disclosed (`includeConsentEntry`).

## 10. Decisions
- **Jared 2026-10-19: all §11 as recommended** — (1) `localStorage`, (2) 6-month expiry (refusals too), (3) embeds stay
  click-to-load independent of the banner, (4) no consent logging, (5) mashandburnco first, then GMF, then inneropen
  develop, (6) non-modal bottom bar + `<dialog>` for Customise, (7) neutral English defaults in MarvinAstro, overridable
  per site; editable in Marvin later (Stage 3 deferred), Jared approves final text, (8) Umami ungated + disclosed as a
  processor, (9) GMF self-hosts its fonts via `@fontsource`.

## 11. Questions for Jared (recommended first)
1. Storage: `localStorage` (rec.) or a first-party cookie (`SameSite=Lax`, apex Domain)?
2. Consent expiry: 6 months (rec., CNIL) or 12? (refusals kept the same time)
3. Embeds: stay click-to-load independent of the banner (rec.) or opt-in auto-load on "marketing" consent?
4. Consent logging: no (rec.) or a minimal no-IP endpoint?
5. First site: mashandburnco (rec.), then GMF, then inneropen develop — or GMF first (the shop)?
6. Banner style: non-modal bottom bar + `<dialog>` for Customise (rec.) or a blocking modal?
7. Default copy: neutral English defaults in MarvinAstro, overridable per site now and editable in Marvin with Stage 3,
   Jared approves final text (rec.) — or Marvin-only copy from day one?
8. Umami: ungated + disclosed under the cookieless exemption (rec.) or gated as `analytics`?
9. GMF Google Fonts: self-host via `@fontsource` (rec.) or keep remote and disclose Google as a processor?
