# Changelog

All notable changes to the Marvin CMS server will be documented in this file.

This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- version list -->

## v1.0.0-rc.243 (2026-10-10)

### Bug Fixes

- **auth**: A session the API rejects goes to the login page too
  ([`547cba3`](https://github.com/InnerOpen/marvin/commit/547cba34413d680039d737b081748411055f48ce))

- **auth**: Find API and site-client tokens by lookup, not by checking every hash
  ([`496e8cf`](https://github.com/InnerOpen/marvin/commit/496e8cf2c957b00767cf6224a501d0b8a8c2b54e))

- **bubble**: The pose prompt says plainly which way to run; the fix for a sheet that didn't
  ([`c73051b`](https://github.com/InnerOpen/marvin/commit/c73051bf6d74724c41efd5867d0c11f95ea47c85))

### Chores

- **dev**: Character kit — Elvira, Fireball Mini, Mossy and Purple Bot
  ([`6648510`](https://github.com/InnerOpen/marvin/commit/66485101fcdace3c16deb458edc647c0fd5a0100))

### Features

- **bubble**: A hand-off's answer keeps the delegate's character; a drop into an edge stops the walk
  ([`3a9d44d`](https://github.com/InnerOpen/marvin/commit/3a9d44d9ae8c4b9b20bbef7a2f611b4701a14bbb))


## v1.0.0-rc.242 (2026-10-10)

### Bug Fixes

- **bubble**: /use shows an agent's character even if it was given one after the page loaded
  ([`4889238`](https://github.com/InnerOpen/marvin/commit/4889238e1e3982744ac6f3f65ce09b718f4c0a5c))


## v1.0.0-rc.241 (2026-10-10)

### Features

- **auth**: Throttle repeated failed sign-ins per account and per IP
  ([`64b2b78`](https://github.com/InnerOpen/marvin/commit/64b2b78867d0dabfbad63de7cd5214454afd39a7))

- **deploy**: Bake the site-wide plugins into the image
  ([`2be28e1`](https://github.com/InnerOpen/marvin/commit/2be28e1ed3220920d7e9b50e245547b1aae76083))


## v1.0.0-rc.240 (2026-10-09)

### Bug Fixes

- **bubble**: A character sheet's shaded background is background too
  ([`2ce91c4`](https://github.com/InnerOpen/marvin/commit/2ce91c4804ccd3139a28fc0ec5169df494623a46))


## v1.0.0-rc.239 (2026-10-09)

### Bug Fixes

- **auth**: An expired login goes to the login page, not "Unauthorized"
  ([`6c521e4`](https://github.com/InnerOpen/marvin/commit/6c521e4b7c684e92fced45e0ad269b842111ef53))

### Continuous Integration

- Log in to Docker Hub before pulling from it
  ([`f2708c2`](https://github.com/InnerOpen/marvin/commit/f2708c2c40a09a6e8e8b4659ffcd74c24caa48e3))


## v1.0.0-rc.238 (2026-10-09)

### Features

- **bubble**: Upload one character sheet, get the whole character
  ([`1a8de0b`](https://github.com/InnerOpen/marvin/commit/1a8de0b9410e8816cb7cb8f29b21cacf8d82ae89))


## v1.0.0-rc.237 (2026-10-09)

### Features

- **dev**: Character kit names each pack's zip after the character
  ([`b0697b4`](https://github.com/InnerOpen/marvin/commit/b0697b4d89f2364f67203d2845e86c7f9755f2ad))


## v1.0.0-rc.236 (2026-10-09)

### Features

- **dev**: Character kit picks each character's background and attaches a layout guide
  ([`7523c6e`](https://github.com/InnerOpen/marvin/commit/7523c6e16a9c1596306c31df27991366bc21c222))


## v1.0.0-rc.235 (2026-10-09)

### Documentation

- **dev**: Keep ChatGPT's Create Pet skill as a character-kit reference
  ([`953ce17`](https://github.com/InnerOpen/marvin/commit/953ce1793b8122d053e213cfe947457ae1131b26))

### Features

- **dev**: Character kit converts ChatGPT pet sprite sheets into packs
  ([`21fc1a4`](https://github.com/InnerOpen/marvin/commit/21fc1a495446e0c901fc0cdafd824dd1f56acbba))


## v1.0.0-rc.234 (2026-10-09)

### Bug Fixes

- **dev**: Character kit keys the background by its real colour, keeping reds and purples
  ([`19f8059`](https://github.com/InnerOpen/marvin/commit/19f805999a83681a0bcc56fe32d014ba1558ea1a))


## v1.0.0-rc.233 (2026-10-09)

### Bug Fixes

- **dev**: Character kit cuts a sheet of big, close poses into all 16
  ([`ad49c7b`](https://github.com/InnerOpen/marvin/commit/ad49c7be8cf5512415c8e4786b03868f72f1bc92))


## v1.0.0-rc.232 (2026-10-09)

### Features

- **dev**: Character kit designs a new character from its description
  ([`f41949c`](https://github.com/InnerOpen/marvin/commit/f41949c56fe334e864310cbaa55396a3ce7a997d))


## v1.0.0-rc.231 (2026-10-09)

### Features

- **dev**: Character kit warns when a pose is cut off, and keeps tilts and jumps in frame
  ([`24083ff`](https://github.com/InnerOpen/marvin/commit/24083ff4ae3b152882a5bd8a6315a2e91a2825c4))


## v1.0.0-rc.230 (2026-10-09)

### Bug Fixes

- **dev**: Character kit side peeks fit any body shape
  ([`9236789`](https://github.com/InnerOpen/marvin/commit/923678957588fc097dcde5d19c54686380f89713))


## v1.0.0-rc.229 (2026-10-09)

### Features

- **dev**: Character kit — a bubble character's whole pack from one pose sheet
  ([`40cb860`](https://github.com/InnerOpen/marvin/commit/40cb8608bd5fc240fc30c1121b13d7ea642aa456))


## v1.0.0-rc.228 (2026-10-09)

### Bug Fixes

- **bubble**: The tab comes back only once a peek has slid all the way in
  ([`d1fcbf4`](https://github.com/InnerOpen/marvin/commit/d1fcbf421edd8863b70fcc4e4b8ea8897a621b55))


## v1.0.0-rc.227 (2026-10-09)

### Bug Fixes

- **bubble**: A peek lines up the drawn ledge with the screen edge
  ([`2584c10`](https://github.com/InnerOpen/marvin/commit/2584c10846c924c0b438b0642a3b9b3218a814a6))

### Features

- **bubble**: Retire the plain peek; the edge peeks are Peek left / right / top / bottom
  ([`be3f0d6`](https://github.com/InnerOpen/marvin/commit/be3f0d6a5eed832687a6266a81b07fdc97e28878))


## v1.0.0-rc.226 (2026-10-09)

### Features

- **bubble**: A peek per edge, and the whole character comes out
  ([`09a8882`](https://github.com/InnerOpen/marvin/commit/09a8882760997a29d9a243b5809ef704eab22bcb))


## v1.0.0-rc.225 (2026-10-09)

### Bug Fixes

- **backup**: An asset deleted during a run is skipped, not a failure
  ([`3adb093`](https://github.com/InnerOpen/marvin/commit/3adb093b9a47f31a3d78c555d61c48c3818513be))

### Documentation

- Workflow Library in the app (phase 2)
  ([`2edc2f2`](https://github.com/InnerOpen/marvin/commit/2edc2f24235316cb61face03520e015211259362))

### Features

- **automation**: Library page
  ([`9b2f685`](https://github.com/InnerOpen/marvin/commit/9b2f685e22a78134f30da3ba23ef63ebc90284d5))

- **automations**: Workflow library endpoints
  ([`5ea7b26`](https://github.com/InnerOpen/marvin/commit/5ea7b263601ec3b8a5510a29177c7e178e296f17))

- **bubble**: BUBBLE_PEEK_SECONDS sets how often a tucked bubble peeks
  ([`f62549d`](https://github.com/InnerOpen/marvin/commit/f62549d17fe60d105c1184829b313f14217055b6))

- **workflows**: Start from a recipe
  ([`aa79cda`](https://github.com/InnerOpen/marvin/commit/aa79cda78c6d2ee891d114d3a9cdd01d30979192))


## v1.0.0-rc.224 (2026-10-09)

### Bug Fixes

- **email**: Platform mail falls back to the platform workspace's SMTP profile
  ([`48a44a5`](https://github.com/InnerOpen/marvin/commit/48a44a52114a097d1b845adb81164cd1bcbca55c))


## v1.0.0-rc.223 (2026-10-09)

### Features

- **bubble**: Pressing a tucked bubble's tab pulls it out under your finger
  ([`a347202`](https://github.com/InnerOpen/marvin/commit/a347202ef679382c98cc77d8d36b28e53f943322))


## v1.0.0-rc.222 (2026-10-09)

### Bug Fixes

- **bubble**: A tucked bubble shows a tab you can see, and doesn't slide across on reload
  ([`42cb589`](https://github.com/InnerOpen/marvin/commit/42cb589d40ea9103f62364d02e767531ffd5998b))


## v1.0.0-rc.221 (2026-10-09)

### Features

- **bubble**: A tucked bubble peeks out now and then
  ([`caccef7`](https://github.com/InnerOpen/marvin/commit/caccef7060122523ba94f7f9166bb720a9db26fe))


## v1.0.0-rc.220 (2026-10-09)

### Features

- **bubble**: Tuck the bubble into a screen edge, and keep it out of the way while scrolling
  ([`5a6b4f0`](https://github.com/InnerOpen/marvin/commit/5a6b4f0cf949779eb80acf38110f8cea346cc5e2))


## v1.0.0-rc.219 (2026-10-09)

### Bug Fixes

- **assets**: The image cropper works with a finger and fits a phone
  ([`ce86ee1`](https://github.com/InnerOpen/marvin/commit/ce86ee1028654676a318daee09e9582181cc010a))


## v1.0.0-rc.218 (2026-10-09)

### Bug Fixes

- **publish**: An entry's assets and resources come in placement order
  ([`0e97378`](https://github.com/InnerOpen/marvin/commit/0e97378465199e6d69373085746846bd54c3f14b))


## v1.0.0-rc.217 (2026-10-08)

### Bug Fixes

- **webhooks**: No Generate key for senders that issue their own, and replace an existing secret on
  ask
  ([`a3605ec`](https://github.com/InnerOpen/marvin/commit/a3605ecbf01c8fe41c730821956bf5aaf4e251d8))


## v1.0.0-rc.216 (2026-10-08)

### Features

- **assets**: Ask files live apart from the Assets library
  ([`53efc4b`](https://github.com/InnerOpen/marvin/commit/53efc4beeb812e825908caa2994dc7857b6e7880))

- **pwa**: The app icon counts waiting approvals, and a notification opens in its workspace
  ([`2128b1b`](https://github.com/InnerOpen/marvin/commit/2128b1b3c773b9de673a2e35823ad645046b3a59))

- **pwa**: Uploads that fail offline wait and send when the connection is back
  ([`8d0639d`](https://github.com/InnerOpen/marvin/commit/8d0639de2402cb31813b64dfed8c47e345ce7d86))

### Refactoring

- **ai**: OpenAI and Azure OpenAI come only from the marvin-ai-openai plugin
  ([`d15c0d8`](https://github.com/InnerOpen/marvin/commit/d15c0d84f39be70aee54d4d12fff128ae311eb84))


## v1.0.0-rc.215 (2026-10-08)

### Bug Fixes

- **bubble**: Sending while listening clears the input for good
  ([`bb28b64`](https://github.com/InnerOpen/marvin/commit/bb28b642155f9cde69e7cfbea8f931fdb271f589))


## v1.0.0-rc.214 (2026-10-08)

### Bug Fixes

- **ai**: Look at attached files before answering about them, and know they are already assets
  ([`feb13c5`](https://github.com/InnerOpen/marvin/commit/feb13c51cf1863670e90337601810cd2013f84f8))

- **bubble**: Speak keeps listening until you stop it
  ([`210b55c`](https://github.com/InnerOpen/marvin/commit/210b55c4dd745903fee28331500ed09879a2edbf))


## v1.0.0-rc.213 (2026-10-08)

### Features

- **bubble**: Attach files and dictate in the bubble
  ([`d3c3210`](https://github.com/InnerOpen/marvin/commit/d3c3210e74eb7a8b146f47cac64b679555b7ca5b))


## v1.0.0-rc.212 (2026-10-08)

### Features

- **ai**: Files attached to an agent question, and read_attachment
  ([`ec12810`](https://github.com/InnerOpen/marvin/commit/ec12810ffc65cdd5498650d2fe0cd775e9b2963b))


## v1.0.0-rc.211 (2026-10-08)

### Bug Fixes

- **deploy**: A release commit doesn't supersede the push that cut it
  ([`973928d`](https://github.com/InnerOpen/marvin/commit/973928d87f440f4bbb458a22fb9a8097996dd158))

- **secrets**: Store a secret in the caller's transaction
  ([`bd59f88`](https://github.com/InnerOpen/marvin/commit/bd59f88010c8893eda51a19683fda3116ac5eaa2))


## v1.0.0-rc.210 (2026-10-08)

### Features

- **ai**: Production uses the marvin-ai-openai plugin for OpenAI and Azure
  ([`175dbfb`](https://github.com/InnerOpen/marvin/commit/175dbfbbbf97adfbf9da8109fb707f912e37b3cc))


## v1.0.0-rc.209 (2026-10-08)

### Bug Fixes

- **frontend**: Email template Save buttons were invisible
  ([`3ccd959`](https://github.com/InnerOpen/marvin/commit/3ccd959777e4d63990bb9dde60b90f1d3ef685a6))

- **frontend**: Email templates and SMTP fit a phone
  ([`b5cf152`](https://github.com/InnerOpen/marvin/commit/b5cf1529280b42d1b02e2dc0ed95438271147793))

- **frontend**: Phone-wide fixes for title rows, page modals and iOS field zoom
  ([`0d00957`](https://github.com/InnerOpen/marvin/commit/0d00957e203de9ecac2118c9dcdbb6823d0d91f0))

- **frontend**: Submission protection fits a phone
  ([`de46b27`](https://github.com/InnerOpen/marvin/commit/de46b2712272e772f9233cc5ce6623a3bcb1f92e))

- **frontend**: The rest of Settings and Automation fit a phone
  ([`293d1db`](https://github.com/InnerOpen/marvin/commit/293d1db0242b09a1eadcaea653ddd69bd61945a9))

### Documentation

- Getting platform alerts outside Marvin
  ([`58a0ae0`](https://github.com/InnerOpen/marvin/commit/58a0ae0bc7b41efbf94440c28942fc4a00b1f97b))


## v1.0.0-rc.208 (2026-10-07)

### Bug Fixes

- **register**: Logged-in visitors go to the workspace (real cookie name)
  ([`d7e67ee`](https://github.com/InnerOpen/marvin/commit/d7e67eef454dfc89474ba88629ec665252da4163))

### Documentation

- Postgres runbook (dev env, CNPG backups/PITR, copy tool, cutover)
  ([`4e0a7c7`](https://github.com/InnerOpen/marvin/commit/4e0a7c7704ebc9f12b3680de32a498f2952c1b14))

### Testing

- The alias migration check reads one row each, no ORDER BY on JSON
  ([`64cb622`](https://github.com/InnerOpen/marvin/commit/64cb6228504e826dfb401c015e676df0a92e95f0))


## v1.0.0-rc.207 (2026-10-06)

### Bug Fixes

- **entries**: Publishing an entry into a smart collection could 500
  ([`9b81965`](https://github.com/InnerOpen/marvin/commit/9b81965a04b9d49b48c7700253bde515b196a4b4))


## v1.0.0-rc.206 (2026-10-06)

### Documentation

- Platform events aren't offered on the workspace side
  ([`5c72319`](https://github.com/InnerOpen/marvin/commit/5c72319c8ded3ec10eae663506d00d463b262620))

- The Events page's Sent by / What happens / Recent (manual + what's new)
  ([`ccc4973`](https://github.com/InnerOpen/marvin/commit/ccc497374ce894bf59f12d17288f67cead144828))

- **tasks**: Events hub slice 4 review
  ([`0edbb8f`](https://github.com/InnerOpen/marvin/commit/0edbb8fa03655b8c18780793d9087e458ec67b9a))

- **tasks**: Events hub slice 4 review — platform events hidden
  ([`2a4846c`](https://github.com/InnerOpen/marvin/commit/2a4846cf26d72e7b4f0a32f729eba9bec7d0089c))

### Features

- **events**: Event page shows what sends it, what happens and when
  ([`76bf30c`](https://github.com/InnerOpen/marvin/commit/76bf30ce28f712cf05f41614f3de0d86032f4a88))

- **events**: The workspace side leaves platform events out
  ([`26672d8`](https://github.com/InnerOpen/marvin/commit/26672d8b134939568c58bdaeb10557ebb86901cd))


## v1.0.0-rc.205 (2026-10-06)

### Documentation

- **tasks**: Events hub slice 3 review
  ([`cee7272`](https://github.com/InnerOpen/marvin/commit/cee7272987f5c65ff2a1932a7854f89cb1e1d984))

### Features

- **events**: One lookup for what sends an event and what reacts to it
  ([`e226a10`](https://github.com/InnerOpen/marvin/commit/e226a10a1667ee327d4c37659b5da0a043d66e67))


## v1.0.0-rc.204 (2026-10-06)

### Documentation

- **tasks**: Events hub slice 2 review; two more sent_by senders
  ([`aa86762`](https://github.com/InnerOpen/marvin/commit/aa86762f51d02f7c04c05fa74309c06f7cc7eb2b))

### Features

- **events**: Catalogue every sent event; one internal-events set
  ([`28ba107`](https://github.com/InnerOpen/marvin/commit/28ba107967386f018a5d8dcc0c6aff0a8f03b8b8))

- **events**: One catalog — triggerable, emittable, sent_by, leads_to
  ([`9adf871`](https://github.com/InnerOpen/marvin/commit/9adf871d49ef9df173dbda0dce6ef35f9eb70cef))

### Testing

- **events**: Drop the retired side-list snapshots
  ([`a7b6e80`](https://github.com/InnerOpen/marvin/commit/a7b6e809e1411b57c5dcdf9e62fa58aaf95e5a69))


## v1.0.0-rc.203 (2026-10-06)

### Bug Fixes

- **db**: Workflow-type webhooks failed to save on Postgres
  ([`29b5c04`](https://github.com/InnerOpen/marvin/commit/29b5c040ae8d2f15760680616c14697b6be788bb))

### Documentation

- Breadcrumb trail on admin and settings pages (manual + what's new)
  ([`3cc9bb8`](https://github.com/InnerOpen/marvin/commit/3cc9bb8159ee0c3ad0aa3029d06bac1898ed8b4f))


## v1.0.0-rc.202 (2026-10-06)

### Bug Fixes

- **frontend**: Admin Events cards hide closed payload rows on a phone
  ([`106e4ff`](https://github.com/InnerOpen/marvin/commit/106e4ffa4d56404ded683dde1167c9e42658a9da))

### Documentation

- Platform events and the admin Events page (manual + what's new)
  ([`b4254c1`](https://github.com/InnerOpen/marvin/commit/b4254c15e634fddb3e827a365f167822e79dee4b))

### Features

- **events**: Platform events leave the workspace Event Log for an admin API
  ([`0db17f4`](https://github.com/InnerOpen/marvin/commit/0db17f482ac7b116840dc43c8602ef488ac3ec0f))

- **frontend**: Admin Events page for platform events
  ([`ca641d9`](https://github.com/InnerOpen/marvin/commit/ca641d9ec7b663faf5ca5af69163f488b41d5d9b))


## v1.0.0-rc.201 (2026-10-06)

### Bug Fixes

- **events**: An audit settings change doesn't queue a site rebuild
  ([`caae4a1`](https://github.com/InnerOpen/marvin/commit/caae4a1084a38a45e349951befe09ec762587119))

### Documentation

- Event Log audit coverage (manual + what's new)
  ([`0e2c0da`](https://github.com/InnerOpen/marvin/commit/0e2c0da1c094f1b311d315dfcc8e427f68fe418c))

### Features

- **events**: Per-workspace audit toggles for the Event Log
  ([`91ede63`](https://github.com/InnerOpen/marvin/commit/91ede63567b6b00768bf20cbbd676b3fad86da66))

- **frontend**: Event Log audit coverage reads and edits the API
  ([`7e10b7d`](https://github.com/InnerOpen/marvin/commit/7e10b7d73a2037c0507432129404667ef45dc703))


## v1.0.0-rc.200 (2026-10-06)

### Bug Fixes

- **tags**: Attaching a tag to an asset or resource returned 500
  ([`7cd788d`](https://github.com/InnerOpen/marvin/commit/7cd788d5d6b9d8e30b4ab1e1f0137cad3d53bb29))


## v1.0.0-rc.199 (2026-10-05)

### Continuous Integration

- Cache pip downloads in the cli, sdk and release workflows
  ([`8d59a18`](https://github.com/InnerOpen/marvin/commit/8d59a1844a2b5b15921e8cc687095f704a76c78a))

- Optional self-hosted runner for push builds (CI_RUNNER)
  ([`5a1bf65`](https://github.com/InnerOpen/marvin/commit/5a1bf657354ef8d657fd930bac7b9360e3e799ad))

- Publish test results with the composite (non-Docker) action
  ([`cb75109`](https://github.com/InnerOpen/marvin/commit/cb751097d6930e587112adc66e80d21d5dc45723))

- Run the PostgreSQL job on GitHub-hosted runners only
  ([`38d6550`](https://github.com/InnerOpen/marvin/commit/38d65504963ca007683ac059e7345a1207bdf583))

### Documentation

- Media embeds (manual, what's new, publishing API); tasks: tick the core plan
  ([`2dee73d`](https://github.com/InnerOpen/marvin/commit/2dee73de9e83bc0c7794d024d8837cfd00be8e09))

- **manual**: Alerts & health page; tasks: tick the plan
  ([`26cd40c`](https://github.com/InnerOpen/marvin/commit/26cd40c8f16396892a24841724edeaf7a8abe510))

### Features

- **publish**: ?expand=full returns full entries from the list endpoints
  ([`2a9d833`](https://github.com/InnerOpen/marvin/commit/2a9d83334de32917fa4a6b80ea8f666d150673c4))


## v1.0.0-rc.198 (2026-10-05)

### Bug Fixes

- **deps**: Declare requests; install the integration SDK in the SDK gate
  ([`ca2b238`](https://github.com/InnerOpen/marvin/commit/ca2b238e7a4f904c699bb5a31b4d012a2fa1b1b6))

### Documentation

- **manual**: Catch up with rc.197: n8n, integration errors, roles
  ([`b6f5349`](https://github.com/InnerOpen/marvin/commit/b6f53499cafb6ab7ddeec83e58fd1ca4b74952a6))

- **manual**: What's new through rc.197
  ([`18d826e`](https://github.com/InnerOpen/marvin/commit/18d826ee99c85edc20a985e463844aaee9502a3c))


## v1.0.0-rc.197 (2026-10-04)

### Bug Fixes

- Logos and admin-gate tests without the integration SDK
  ([`cb178f7`](https://github.com/InnerOpen/marvin/commit/cb178f7b1a80d012ceba4be18d5b268abfec614a))

### Chores

- **deploy**: Install the n8n integration on iwobble
  ([`172aad4`](https://github.com/InnerOpen/marvin/commit/172aad44ec0e6156f16602a03cdd7755204b8dd8))

### Documentation

- Behaviour changes and retry-chain rules for integration errors
  ([`2807314`](https://github.com/InnerOpen/marvin/commit/28073148480dd80029fc0eb9494a05d34b4a99fe))


## v1.0.0-rc.196 (2026-10-04)

### Features

- **admin**: The entry page says why an entry is waiting for review
  ([`41137fc`](https://github.com/InnerOpen/marvin/commit/41137fc9c950aad5eecf1ac7dd1a724c46e22f59))


## v1.0.0-rc.195 (2026-10-04)

### Features

- **admin**: Voice field on the New entry type page
  ([`1e23da7`](https://github.com/InnerOpen/marvin/commit/1e23da76c4e644bdd3aa54ac819cf5d3fd115b0a))

- **ai**: Preview the prompt of an agent before it is saved
  ([`f0241f4`](https://github.com/InnerOpen/marvin/commit/f0241f4181645dffd63c795fa854137792af4e01))


## v1.0.0-rc.194 (2026-10-04)

### Bug Fixes

- **admin**: Disable View on site until the entry is published
  ([`6ff8b4a`](https://github.com/InnerOpen/marvin/commit/6ff8b4a89a262f019ed93ebebc66e6cb5b1a05c2))

- **ai**: Say Character and Voice where the labels still paired voice/tone
  ([`54bc598`](https://github.com/InnerOpen/marvin/commit/54bc5987a8fc74a63b418def810a0eeda42e7251))

### Documentation

- **manual**: Prompt previews and the Character / Voice labels
  ([`c7f091d`](https://github.com/InnerOpen/marvin/commit/c7f091d15626a6e9e4f952c9462f4b1f1995752e))

### Features

- **admin**: Prompt previews on tone rows, the Character and agents
  ([`800612b`](https://github.com/InnerOpen/marvin/commit/800612b1c1a758016342b8187c2b32bad7866874))

- **ai**: Preview an agent's system prompt and the Character with the default tone
  ([`d862782`](https://github.com/InnerOpen/marvin/commit/d862782ed12b8e57ad1f899e235d82285bfbd7ec))


## v1.0.0-rc.193 (2026-10-04)

### Features

- **dashboard**: Count Needs review and show why on the Review Queue's cards
  ([`3ebd320`](https://github.com/InnerOpen/marvin/commit/3ebd320c59ba55350560872c40b17eea288d017f))

- **workflows**: On_failure steps, a request_review entry op and coded integration errors
  ([`79fa3d0`](https://github.com/InnerOpen/marvin/commit/79fa3d07b7ff248e7af4c38c1228bd623a28ca72))


## v1.0.0-rc.192 (2026-10-04)

### Bug Fixes

- **admin**: Keep the Ask page's hidden attachment chip hidden
  ([`11ed7c9`](https://github.com/InnerOpen/marvin/commit/11ed7c95008a32fdbcfc7542f0148a805da7f774))

### Features

- **admin**: Collapse the entry editor's raw JSON fields by default
  ([`92c3ad3`](https://github.com/InnerOpen/marvin/commit/92c3ad3c4ffe69a0def5d634d9be6f694037cdf1))

- **ai**: Label the persona as Character and let the tone win on delivery
  ([`1b1a78a`](https://github.com/InnerOpen/marvin/commit/1b1a78ac73354ab10fa9b3edad6d306d74e47875))


## v1.0.0-rc.191 (2026-10-04)

### Bug Fixes

- **publishing**: Don't queue site rebuilds for changes no site can see
  ([`e592989`](https://github.com/InnerOpen/marvin/commit/e5929899c992bf7de1785d530b02e43bb09f00c5))


## v1.0.0-rc.190 (2026-10-04)

### Bug Fixes

- **ai**: End, refuse or re-check a carried-up ask where resuming could go wrong
  ([`a6dd2a3`](https://github.com/InnerOpen/marvin/commit/a6dd2a37161e67062bab4d838a68fbf07a8019a6))

### Documentation

- A specialist's ask carried up to Marvin; tasks: C2 checklist and review
  ([`329ac29`](https://github.com/InnerOpen/marvin/commit/329ac293d9df7be088bfea02dd40ea97520b8bc0))

### Features

- **admin**: Approve a specialist's ask from the Ask page, the bubble or a toast
  ([`2595766`](https://github.com/InnerOpen/marvin/commit/25957666e0a164a2f51fbaa6c97ba6bcb178a668))

- **ai**: Bubble tool list follows Marvin's matrix; drafts use the run's tone
  ([`04fc46f`](https://github.com/InnerOpen/marvin/commit/04fc46f44e908e486c55bfa1187afeb97282a1f2))

- **ai**: Carry a specialist's ask up to Marvin
  ([`15d9e55`](https://github.com/InnerOpen/marvin/commit/15d9e556c273d49bc18e42b22201ee1aaa29e12a))

### Testing

- **admin**: Resume source checks follow the bubble's approval card
  ([`829ab14`](https://github.com/InnerOpen/marvin/commit/829ab14a33f35619a14d1e0cd409835192f38a05))


## v1.0.0-rc.189 (2026-10-04)

### Refactoring

- Remove the built-in Apprise notifier — use the Apprise integration
  ([`9ab9f40`](https://github.com/InnerOpen/marvin/commit/9ab9f40bbe6996764d8cc82cbcc1b436e069eb2e))

### Breaking Changes

- The /api/group/notifications and /api/event/options endpoints, the APPRISE_ENABLED / APPRISE_URL
  settings and the about endpoints' Apprise fields are gone. Send notifications by connecting the
  Apprise integration's notify action to events instead.


## v1.0.0-rc.188 (2026-10-04)

### Documentation

- Custom tones in the manual; tasks: tones checklist done
  ([`d3746ad`](https://github.com/InnerOpen/marvin/commit/d3746ad02c7b4fb9b46ff90c198949b142baca85))

- **manual**: Admin pages by their grouped sidebar names
  ([`fe10353`](https://github.com/InnerOpen/marvin/commit/fe10353c93be4dfa6a1211e0442d451232a3ae31))

- **manual**: Agents and Ask through rc.185
  ([`b245e59`](https://github.com/InnerOpen/marvin/commit/b245e59fd8a85b3f50ea0aed09388b2dd96fac48))

- **manual**: API clients, token dialogs and admin-only secrets
  ([`630417c`](https://github.com/InnerOpen/marvin/commit/630417c83b480a3fd676c84c87a477a6af95db56))

- **manual**: Operations and the admin shell through rc.186
  ([`c835b71`](https://github.com/InnerOpen/marvin/commit/c835b713581848d5f3b8932a547891343326ac1b))

- **manual**: Plugins page, HTTP patch and the Buttondown provider
  ([`64ea2d7`](https://github.com/InnerOpen/marvin/commit/64ea2d7a322c4438dc1ffdd8febe75862f1b78bf))

- **manual**: Scheduled publishing, private collections and client permissions
  ([`8291b8e`](https://github.com/InnerOpen/marvin/commit/8291b8ee6327683de1c8bef02c10100d4bf51f1b))

- **manual**: What's new and workflows provenance through rc.186
  ([`3dd9964`](https://github.com/InnerOpen/marvin/commit/3dd99642a47265d4c39ca208847449a6b8d3eaea))

### Features

- **admin**: Tones editor, tone pickers and the bubble's /tone
  ([`2d7ebc9`](https://github.com/InnerOpen/marvin/commit/2d7ebc9625ff60eb31f380b2131d9efe9b592607))

- **ai**: Custom tones per workspace
  ([`9168bc9`](https://github.com/InnerOpen/marvin/commit/9168bc94351aa735193a4fa746030d9e8f419d65))


## v1.0.0-rc.187 (2026-10-04)

### Bug Fixes

- **ai**: Bind the bubble's Marvin through Marvin's permission matrix
  ([`f040df4`](https://github.com/InnerOpen/marvin/commit/f040df4906ca9787e0078086ad42c0fe0918111b))


## v1.0.0-rc.186 (2026-10-04)

### Features

- **collections**: "Visible to sites" toggle for a collection's is_public flag
  ([`af9e609`](https://github.com/InnerOpen/marvin/commit/af9e609ad4c5cf956555042c3fdb4ae9d3334b65))


## v1.0.0-rc.185 (2026-10-04)

### Features

- **ai**: Separate invocation-source toggles for the bubble and the Ask page
  ([`30e2aa9`](https://github.com/InnerOpen/marvin/commit/30e2aa9a2a9a36ce93ca15ea710db096657b2a4f))


## v1.0.0-rc.184 (2026-10-04)

### Bug Fixes

- **frontend**: The Ask bubble hides when "Ask {assistant}" is switched off
  ([`24b778e`](https://github.com/InnerOpen/marvin/commit/24b778e36b44af3fa534babaa77ed2a1e8b67525))


## v1.0.0-rc.183 (2026-10-04)

### Bug Fixes

- **frontend**: Remove the unused API-client create route that put the token in a URL
  ([`4910f83`](https://github.com/InnerOpen/marvin/commit/4910f83216e1629a5ddd4d26474cfa9e5652c9d5))

- **frontend**: Show new personal API tokens once in a dialog, never in the URL
  ([`7a3998a`](https://github.com/InnerOpen/marvin/commit/7a3998ae175c820739c09015fc4a46869d5f44a3))


## v1.0.0-rc.182 (2026-10-04)

### Bug Fixes

- **api**: Make API client routes workspace-admin only
  ([`4a60bb5`](https://github.com/InnerOpen/marvin/commit/4a60bb5e6ca47bdf7167b44529b4f9508dad2ad8))

- **api**: Only workspace admins may create, change or delete secrets
  ([`fddde25`](https://github.com/InnerOpen/marvin/commit/fddde25f5d46987d542979dccdb8c295747b1bdd))

### Features

- **integrations**: PATCH on the provider HTTP helper
  ([`51bf42a`](https://github.com/InnerOpen/marvin/commit/51bf42ab2e806ecb333809c2300908a2654658b7))


## v1.0.0-rc.181 (2026-10-04)

### Features

- **api**: Refuse to delete an enabled API client
  ([`c09fc5e`](https://github.com/InnerOpen/marvin/commit/c09fc5e4513003f528e3fd8a828d241837d8df60))

- **frontend**: Edit and delete API clients, offer form-submit permissions
  ([`ff6417d`](https://github.com/InnerOpen/marvin/commit/ff6417d732cae1d2f8e2fa417586f254750f57a8))


## v1.0.0-rc.180 (2026-10-04)

### Features

- **ai**: Bubble lines written from the workspace persona
  ([`0d9b662`](https://github.com/InnerOpen/marvin/commit/0d9b662c97e6448ec70e390dbc7f76cdc2837481))

- **frontend**: The bubble speaks the workspace's own lines; AI settings edit them
  ([`7741350`](https://github.com/InnerOpen/marvin/commit/7741350876620f7b7805406b9f8af474261b59e9))


## v1.0.0-rc.179 (2026-10-04)

### Features

- **workflows**: Entry step if_none: skip, and ${entry.url}
  ([`2b462fc`](https://github.com/InnerOpen/marvin/commit/2b462fcce36ea8661197ea4516c7bfeb0c8bd4d4))


## v1.0.0-rc.178 (2026-10-04)

### Chores

- **chart**: Install the Buttondown integration on iwobble
  ([`c86844a`](https://github.com/InnerOpen/marvin/commit/c86844a4058212b28cd784a2f98f2dd4faf181ea))

### Features

- **events**: Every event names its subject; a workflow run names its trigger and steps
  ([`d04dc84`](https://github.com/InnerOpen/marvin/commit/d04dc842901b5deff5867c133ff183c565051b1b))

- **frontend**: The event log links each event's subject and a workflow run's trigger
  ([`a45159e`](https://github.com/InnerOpen/marvin/commit/a45159e542c2a1ae4a9e974e776ae91e312227bd))

### Testing

- **events**: The fake session answers the ${site.url} preferences query
  ([`d45253b`](https://github.com/InnerOpen/marvin/commit/d45253b02348417a03a91d25aaaa65f9d8fc82df))


## v1.0.0-rc.177 (2026-10-04)

### Features

- **workflows**: ${site.url} in the workflow context
  ([`eba285b`](https://github.com/InnerOpen/marvin/commit/eba285b471a0b86ff9c3f9c55d62a94712fb8932))


## v1.0.0-rc.176 (2026-10-04)

### Features

- **frontend**: Refused saves show why and keep your edits; a waiting scheduled publish is shown
  ([`69a0884`](https://github.com/InnerOpen/marvin/commit/69a088418ff027176cb70279bff7f9515b8107da))

- **scheduler**: A held-back scheduled publish says why, once, and can wait for approval
  ([`28e62c8`](https://github.com/InnerOpen/marvin/commit/28e62c898b5e3ef994ef9e714679e5474a9076bf))


## v1.0.0-rc.175 (2026-10-04)

### Bug Fixes

- **scheduler**: Expiry consumes the expiration date, and a passed one blocks publishing
  ([`b2952b3`](https://github.com/InnerOpen/marvin/commit/b2952b3669869f50245e68d9dc6d0f988a0b9651))

### Features

- **frontend**: The entry editor flags an expiration date that has passed
  ([`890afc3`](https://github.com/InnerOpen/marvin/commit/890afc379da64bee8ff27da747133ccaf2da2783))


## v1.0.0-rc.174 (2026-10-04)

### Bug Fixes

- **frontend**: Activity toasts stay on screen on a phone
  ([`3f1e457`](https://github.com/InnerOpen/marvin/commit/3f1e4578ff05f1cad266cb3fa3a61db211c9c297))

- **frontend**: The Marvin bubble rests bottom-left and stays put on screen
  ([`697d301`](https://github.com/InnerOpen/marvin/commit/697d301c35d4146192ba7e252090ef0b3321499a))

### Features

- **frontend**: The admin fits a phone — sidebar drawer, stacked layouts, no sideways scroll
  ([`7fdae61`](https://github.com/InnerOpen/marvin/commit/7fdae619918abcdf46fd2ac0bb103de7f79d84d0))


## v1.0.0-rc.173 (2026-10-04)

### Features

- **frontend**: Workflow dry run picks its sample event and shows the condition checklist
  ([`eb0a510`](https://github.com/InnerOpen/marvin/commit/eb0a510a8fb4ea6156730ebfc7cec5d1e3c67519))

- **workflows**: Dry-run an event-triggered workflow against a sample event
  ([`68ca709`](https://github.com/InnerOpen/marvin/commit/68ca7095db4bc686fa1827bc552782bc13db1d90))


## v1.0.0-rc.172 (2026-10-04)

### Features

- **entries**: A page URL pattern per entry type gives each entry its site URL
  ([`f11a641`](https://github.com/InnerOpen/marvin/commit/f11a6412674ba29036bfd8cb38ad738655840eb4))

- **entries**: Placeholder links like [title](#) block publishing
  ([`153d9da`](https://github.com/InnerOpen/marvin/commit/153d9daba1cc9486831d4158ebce423c0456a874))


## v1.0.0-rc.171 (2026-10-03)

### Bug Fixes

- **scheduler**: Scheduled publish and expiry fire the same entry events as a manual change
  ([`d593ea9`](https://github.com/InnerOpen/marvin/commit/d593ea980b25c0dd3826390a552c71f963c6e9e5))


## v1.0.0-rc.170 (2026-10-03)

### Bug Fixes

- **entries**: Publishing by any route clears the schedule
  ([`02ce26a`](https://github.com/InnerOpen/marvin/commit/02ce26a2ca53e0074967cd5a6b9397f65da2c53b))

### Features

- **scheduler**: Scheduled publish and expiry run out of the box as system tasks
  ([`0e3725d`](https://github.com/InnerOpen/marvin/commit/0e3725d9cde63af6e6452b50580772c3aa6b90ea))


## v1.0.0-rc.169 (2026-10-03)

### Features

- **collections**: A rule builder and Run Query on the smart-collection form
  ([`07601ea`](https://github.com/InnerOpen/marvin/commit/07601ea70c3fc673d9178d5e3543c58c89c3cc45))

- **collections**: Field conditions in smart rules, and a preview of unsaved rules
  ([`62edd8c`](https://github.com/InnerOpen/marvin/commit/62edd8cca2a50ab8e133fe424e82f82b9900f9dc))


## v1.0.0-rc.168 (2026-10-03)

### Bug Fixes

- **entries**: Scheduled Publish and Expiration dates save, in the viewer's time zone
  ([`9e39a1b`](https://github.com/InnerOpen/marvin/commit/9e39a1b05936852e55c1b24047990ab7c90baeef))

- **scheduler**: Scheduled publish runs once and leaves archived entries alone
  ([`7d6aec2`](https://github.com/InnerOpen/marvin/commit/7d6aec2725a14e8f2b579737edcef0e2ecf88968))


## v1.0.0-rc.167 (2026-10-03)

### Features

- **frontend**: Attached images preview at the top of Entry Details
  ([`d9aec37`](https://github.com/InnerOpen/marvin/commit/d9aec3775e9ada0e858bcf74499cfd52c4b60689))


## v1.0.0-rc.166 (2026-10-03)

### Features

- **ai**: Search and read Marvin's own manual from agents (search_docs, read_doc)
  ([`47182a9`](https://github.com/InnerOpen/marvin/commit/47182a98e3bd3d32bcaa40c5e76cc46f17705375))


## v1.0.0-rc.165 (2026-10-03)

### Features

- **activity**: Queued-rebuild and running-workflow toasts that update in place
  ([`4bb6ed6`](https://github.com/InnerOpen/marvin/commit/4bb6ed6d3da2b5dcc698cd56cc4252f235fa7977))


## v1.0.0-rc.164 (2026-10-03)

### Bug Fixes

- **ui**: Dark mode applies before the first paint — no white flash
  ([`a00c97f`](https://github.com/InnerOpen/marvin/commit/a00c97fabaf3cf176a2c804f61de73e7cab4b43d))


## v1.0.0-rc.163 (2026-10-03)

### Chores

- **deploy**: The backend deploys with Recreate on iwobble
  ([`5762700`](https://github.com/InnerOpen/marvin/commit/57627009310c4fcb0eb811320a70b2332a79bb72))

### Features

- **ai**: The Ask page lists every agent's threads, hand-offs nested under their parent
  ([`c216b84`](https://github.com/InnerOpen/marvin/commit/c216b84e69d39043e54922e363e11220c1364db1))


## v1.0.0-rc.162 (2026-10-03)

### Bug Fixes

- **ai**: Big bulk writes ask first, tagging uses the images, restart-killed runs are marked,
  deploys drain
  ([`8dbc749`](https://github.com/InnerOpen/marvin/commit/8dbc749cbbf228fb197c88c71a44ca962d2c59b3))

- **ui**: The update banner shows on admin pages too
  ([`0ad5707`](https://github.com/InnerOpen/marvin/commit/0ad570706cf8c2d3e3e358fad3e697638d2deb08))


## v1.0.0-rc.161 (2026-10-03)

### Features

- **ui**: An agent's Character button opens its bubble character without Edit
  ([`6b82d98`](https://github.com/InnerOpen/marvin/commit/6b82d98fb82320feeae524e8b380d7f499073abc))


## v1.0.0-rc.160 (2026-10-03)

### Features

- **admin**: "What's new" list on the update banner
  ([`b9c022c`](https://github.com/InnerOpen/marvin/commit/b9c022c884c4c48a65e86b0df5abd3161a1f1eaf))

- **admin**: List the image's unreleased commits in "What's new"
  ([`315e0ce`](https://github.com/InnerOpen/marvin/commit/315e0ce99069e70ad013ee9fb48688879cb96cef))

- **ui**: An agent's bubble character sits in its Edit form, under Icon and Name
  ([`7e02d7c`](https://github.com/InnerOpen/marvin/commit/7e02d7c6e9c3091515a2bf5da0d737ac9e878b04))


## v1.0.0-rc.159 (2026-10-03)

### Bug Fixes

- **character**: Clear solid backgrounds from bubble-character images
  ([`4929ec5`](https://github.com/InnerOpen/marvin/commit/4929ec59564c8ba3e68eb777c31f02888f5c4db9))

### Features

- **admin**: Delete a character pack from its card, even one in use
  ([`f29fdbf`](https://github.com/InnerOpen/marvin/commit/f29fdbfe72cef571768581a0085c3ae9a7e591e0))


## v1.0.0-rc.158 (2026-10-03)

### Features

- **admin**: Group the admin nav, turn /admin into an overview, add a plugins page
  ([`dffdd86`](https://github.com/InnerOpen/marvin/commit/dffdd8682c5877d2a0207edef66ad28aa0ba6923))


## v1.0.0-rc.157 (2026-10-03)

### Documentation

- Publish the Marvin manual
  ([`888ba85`](https://github.com/InnerOpen/marvin/commit/888ba85da32a4008ff6df49fa52f30395a3d0fa2))

### Features

- **ui**: Pick a bubble character from cards, not a dropdown
  ([`27b56db`](https://github.com/InnerOpen/marvin/commit/27b56db49d4575d267df1f8eadfd3738410c5247))


## v1.0.0-rc.156 (2026-10-03)

### Bug Fixes

- **bubble**: Keep threads per workspace; recover from a 404'd thread
  ([`6bc32ec`](https://github.com/InnerOpen/marvin/commit/6bc32ecc0702a1a85d754029facdd2c086b57618))

### Features

- **ai**: Character library and per-agent bubble characters
  ([`c31228e`](https://github.com/InnerOpen/marvin/commit/c31228ecafdc03216956db4e7d4192f20ffb103a))


## v1.0.0-rc.155 (2026-10-03)

### Bug Fixes

- **events**: Webhook_triggered's catalog entry describes what it carries
  ([`b2d7ac9`](https://github.com/InnerOpen/marvin/commit/b2d7ac9f871fbce0ad2e07011c0f270bc81084e8))


## v1.0.0-rc.154 (2026-10-03)

### Features

- **publishing**: Site rebuild toast lists what changed
  ([`317c509`](https://github.com/InnerOpen/marvin/commit/317c50970b487d690fe81e5a1c2c7caedc9109d1))


## v1.0.0-rc.153 (2026-10-03)

### Features

- **ai**: Animated bubble character — one animation per bubble state
  ([`e5c3efc`](https://github.com/InnerOpen/marvin/commit/e5c3efcb8178364e1b85da39bdcab00170de8fba))


## v1.0.0-rc.152 (2026-10-03)

### Bug Fixes

- **automation**: Site build/deploy events are workflow triggers
  ([`a62d97f`](https://github.com/InnerOpen/marvin/commit/a62d97ff79d0656d6b1850bfb690ae04fa9aa1ed))


## v1.0.0-rc.151 (2026-10-03)

### Bug Fixes

- **events**: Site build/deploy events can trigger workflows and notifications
  ([`31b5266`](https://github.com/InnerOpen/marvin/commit/31b52661cc0ca3acb08a8bf5fc4d54036d14522b))


## v1.0.0-rc.150 (2026-10-03)

### Features

- **ai**: Bubble agent runs live in server threads and survive navigation
  ([`ef103f7`](https://github.com/InnerOpen/marvin/commit/ef103f72c6f140ecacd17455958e89b141096b5e))


## v1.0.0-rc.149 (2026-10-03)

### Bug Fixes

- **dashboard**: Count inbox and drafts apart in Needs Attention
  ([`1fc74f1`](https://github.com/InnerOpen/marvin/commit/1fc74f18e8ba9b1623b633150afe274153319351))

### Refactoring

- **ai**: Official OpenAI via the Responses API; no per-model rules
  ([`03a62bb`](https://github.com/InnerOpen/marvin/commit/03a62bb5fa253438342c440d46bb48d2011eddbc))


## v1.0.0-rc.148 (2026-10-03)

### Bug Fixes

- **ai**: Send tool calls through the Responses API when a model asks
  ([`f5a7a5e`](https://github.com/InnerOpen/marvin/commit/f5a7a5ed6aba64c4a11c76aa1c30088f099b256e))


## v1.0.0-rc.147 (2026-10-03)

### Bug Fixes

- **ai**: Learn which length/sampling parameters a model accepts
  ([`7d217ce`](https://github.com/InnerOpen/marvin/commit/7d217cec79f33c83ff933c954de070e7039221a3))


## v1.0.0-rc.146 (2026-10-03)

### Chores

- **deploy**: Install the Cloudflare Pages integration on iwobble
  ([`d721731`](https://github.com/InnerOpen/marvin/commit/d7217316ab07ffdb4c599e5a568b121c9ad805f7))

### Features

- **ai**: AI usage against limits, honest external sources, agent names in history
  ([`7871997`](https://github.com/InnerOpen/marvin/commit/787199766b297eaf293009df2e5b65092f43a284))


## v1.0.0-rc.145 (2026-10-03)

### Features

- **integrations**: {{SECRET}} references in integration action arguments
  ([`a9daeda`](https://github.com/InnerOpen/marvin/commit/a9daedaa80fa14d92abd15b38ce662dd2bd17391))


## v1.0.0-rc.144 (2026-10-03)

### Features

- Site build/deploy status from a host's webhook, as Marvin events and toasts
  ([`3ef20e4`](https://github.com/InnerOpen/marvin/commit/3ef20e4fb86f32d80d20beae235087057cb22522))


## v1.0.0-rc.143 (2026-10-03)

### Features

- **publishing**: Published content changes rebuild the site on their own
  ([`5c70383`](https://github.com/InnerOpen/marvin/commit/5c70383acb0fea55ffd9a926c047eedca92d4d23))


## v1.0.0-rc.142 (2026-10-03)

### Bug Fixes

- **ai**: The search index holds published entries only, and skips unchanged saves
  ([`7136ac8`](https://github.com/InnerOpen/marvin/commit/7136ac8cdb910ce7ff3467e0562678871bc66730))


## v1.0.0-rc.141 (2026-10-03)

### Features

- **ai**: Workspace reindex runs in the background, batched and incremental
  ([`33d3b7f`](https://github.com/InnerOpen/marvin/commit/33d3b7f5438cd98a606e2a67cb17c86f66262f1c))


## v1.0.0-rc.140 (2026-10-03)

### Bug Fixes

- **ai**: The main agent carries the workspace's assistant name
  ([`8489865`](https://github.com/InnerOpen/marvin/commit/84898654f79b8b701d9471a0a99d52ffd2792a5d))


## v1.0.0-rc.139 (2026-10-03)

### Bug Fixes

- Bugs the manual review found — fail-closed where ops, apply_many connection, recorded chat runs,
  stale UI copy
  ([`f08d0c2`](https://github.com/InnerOpen/marvin/commit/f08d0c2495a75c9c8fe5ea13ec4a6b4f8f39a9d3))


## v1.0.0-rc.138 (2026-10-02)

### Features

- **entries**: One entry query for agents, workflows and bulk actions
  ([`1c5dcbe`](https://github.com/InnerOpen/marvin/commit/1c5dcbeb504a10a27b9807d057c4772ce99bbc17))


## v1.0.0-rc.137 (2026-10-02)

### Bug Fixes

- **ai**: Keep core tool text workspace-agnostic
  ([`85a03a7`](https://github.com/InnerOpen/marvin/commit/85a03a7267b51134f60d58c6d045a9c49a71ad0b))


## v1.0.0-rc.136 (2026-10-02)

### Bug Fixes

- **ai**: Find_entries can filter and read an entry type's own fields
  ([`2ef0b34`](https://github.com/InnerOpen/marvin/commit/2ef0b348d46cc7ccbfe4f5b1896bea7a1dc0691f))


## v1.0.0-rc.135 (2026-10-02)

### Features

- **ai**: The bubble wears the workspace's assistant name and icon
  ([`1a9dcc6`](https://github.com/InnerOpen/marvin/commit/1a9dcc61001ca883eab1118bdc4a3b5b083d2bb5))


## v1.0.0-rc.134 (2026-10-02)

### Bug Fixes

- **ai**: Approval mode covers every AI write-back; Ask Marvin is the agent source
  ([`6a8dd36`](https://github.com/InnerOpen/marvin/commit/6a8dd360aae03dbba4a414a07193c60e66272b63))


## v1.0.0-rc.133 (2026-10-02)

### Bug Fixes

- **ai**: A blank persona means Marvin's default voice, as the settings page says
  ([`5b2b45d`](https://github.com/InnerOpen/marvin/commit/5b2b45d7264541efa0d9a9bd717cc98c0626a1cd))


## v1.0.0-rc.132 (2026-10-02)

### Bug Fixes

- **automation**: Set_data reads the entry type defensively
  ([`28a6d27`](https://github.com/InnerOpen/marvin/commit/28a6d27f5bb9e6ea7642479949639e46f40eae3d))


## v1.0.0-rc.131 (2026-10-02)

### Bug Fixes

- **automation**: Typed-in values meet checkbox and number fields
  ([`c3ac416`](https://github.com/InnerOpen/marvin/commit/c3ac41665c3735c4e47ef51d7d08e01eea1c3fcf))


## v1.0.0-rc.130 (2026-10-02)

### Bug Fixes

- **automation**: Entry queries de-duplicate by id, so they work on Postgres
  ([`01c4226`](https://github.com/InnerOpen/marvin/commit/01c4226e311fb507429f90665462644814d33d26))


## v1.0.0-rc.129 (2026-10-02)

### Bug Fixes

- **automation**: Query runs see each entry's fields, and can filter by them
  ([`0e254e4`](https://github.com/InnerOpen/marvin/commit/0e254e4c8bac33998b040bf9c571033e3d6a20bb))


## v1.0.0-rc.128 (2026-10-02)

### Features

- **admin**: Activity toasts hang off the bell like a speech bubble
  ([`8177f37`](https://github.com/InnerOpen/marvin/commit/8177f3751eb5358e4df0c055d0beee3d0ed65422))


## v1.0.0-rc.127 (2026-10-02)

### Features

- **admin**: Centre the activity toasts under the top bar
  ([`5f853a2`](https://github.com/InnerOpen/marvin/commit/5f853a298cb6d23fb1333231a9a3a4de13926ca2))


## v1.0.0-rc.126 (2026-10-02)

### Bug Fixes

- **admin**: Show activity toasts in the window corner, not above the top bar
  ([`ca8b18e`](https://github.com/InnerOpen/marvin/commit/ca8b18e64a3f9d4a45057033fa83a927ca6e6db2))


## v1.0.0-rc.125 (2026-10-02)

### Bug Fixes

- **admin**: Style the activity toasts
  ([`de47dfc`](https://github.com/InnerOpen/marvin/commit/de47dfcd2e0069c764ba182fd9036fcc09e73616))


## v1.0.0-rc.124 (2026-10-02)

### Chores

- **deploy**: Iwobble allows 16 MiB integration downloads (Square item pictures)
  ([`151325f`](https://github.com/InnerOpen/marvin/commit/151325fca2879dcb1ed891ae7a4eb995bef9b33b))

### Features

- **admin**: Live activity toasts
  ([`378a10d`](https://github.com/InnerOpen/marvin/commit/378a10d6642e4c47fe5633c0ca2b6c2928f3c487))


## v1.0.0-rc.123 (2026-10-02)

### Features

- **integrations**: INTEGRATION_HTTP_MAX_BYTES caps provider downloads
  ([`1fd3bd8`](https://github.com/InnerOpen/marvin/commit/1fd3bd812618d716d65548bc97c67569d685f64f))


## v1.0.0-rc.122 (2026-10-02)

### Features

- **publishing**: Site rebuild debounce windows are env settings
  ([`e636672`](https://github.com/InnerOpen/marvin/commit/e636672b8a1497a2c684fee6d2f4478d7834a42e))


## v1.0.0-rc.121 (2026-10-02)

### Features

- **publishing**: Coalesce site rebuild requests per workspace
  ([`322d0bf`](https://github.com/InnerOpen/marvin/commit/322d0bfbad52a8d8edfc39ae152f230e9bea21ed))


## v1.0.0-rc.120 (2026-10-02)

### Bug Fixes

- **marvin-bubble**: Open on the latest turn of a restored conversation
  ([`21a6114`](https://github.com/InnerOpen/marvin/commit/21a6114f84f6669f5841156095e1175f464b0249))


## v1.0.0-rc.119 (2026-10-02)

### Features

- **automation**: Workflows see the entry's featured image URL; integration HTTP sends a named
  User-Agent
  ([`c4691e6`](https://github.com/InnerOpen/marvin/commit/c4691e617cbc6f599b44d64e4056af8d147229e4))


## v1.0.0-rc.118 (2026-10-02)

### Features

- **blueprints**: Update an applied workflow to its integration's current version
  ([`d874a58`](https://github.com/InnerOpen/marvin/commit/d874a58d65dcad3942b33681e42a41523701b1ec))


## v1.0.0-rc.117 (2026-10-02)

### Bug Fixes

- **blueprints**: An integration parameter defaults to the workspace's own connection
  ([`145dfbe`](https://github.com/InnerOpen/marvin/commit/145dfbe0d3cbb308702bca3044cec3faf873ba7b))


## v1.0.0-rc.116 (2026-10-02)

### Features

- **blueprints**: Pick parameters from dropdowns — entry types, collections, integrations
  ([`c6e8547`](https://github.com/InnerOpen/marvin/commit/c6e8547219a2f1ade10218636512073b6aa3d381))


## v1.0.0-rc.115 (2026-10-02)

### Features

- **integrations**: Edit a connected integration; keep Add buttons on the right
  ([`ace1355`](https://github.com/InnerOpen/marvin/commit/ace1355e5547d166fefd222c28ffeb167eeb8668))


## v1.0.0-rc.114 (2026-10-02)

### Bug Fixes

- **integrations**: Apply parameterised content from the card, show action results, {{SECRET}}
  credentials
  ([`4a8cba5`](https://github.com/InnerOpen/marvin/commit/4a8cba51c476c85e2e74eea5589e14c84e653df7))


## v1.0.0-rc.113 (2026-10-02)

### Features

- **hooks**: One general webhook-signature engine — core presets, integration presets, custom
  ([`ddac9b1`](https://github.com/InnerOpen/marvin/commit/ddac9b1d23bc95e46ebb1d8660cee9640ffb4056))


## v1.0.0-rc.112 (2026-10-02)

### Bug Fixes

- **auth**: Workspace admins got a 500 on workflows, webhooks and AI settings
  ([`0c58086`](https://github.com/InnerOpen/marvin/commit/0c58086be3f44a9eedbcdbadf6bb4bfaa3d71a1c))

### Testing

- **integrations**: Skip the HTTP helper tests when the optional SDK is absent
  ([`82c7e04`](https://github.com/InnerOpen/marvin/commit/82c7e048ee514a4f5003089cdd81055daf86ef5b))


## v1.0.0-rc.111 (2026-10-02)

### Chores

- **deploy**: Install the Square integration on iwobble; plans for Trash, dev+Postgres and Square
  ([`f8ee69e`](https://github.com/InnerOpen/marvin/commit/f8ee69ebb93b96c96db266e8c6c79125c7c72485))

### Code Style

- **blueprints**: Ruff format apply.py
  ([`f687421`](https://github.com/InnerOpen/marvin/commit/f687421b4764cb2ae2c1d4ef6c9f86a63e47ccc5))

- **tests**: Ruff format the member-role, set_data and signature tests
  ([`c724d9c`](https://github.com/InnerOpen/marvin/commit/c724d9c46c9e9ad6e3f2023521ee7c3b37df13ed))

### Features

- **automation**: Integration workflow step — run a provider action, keep its result
  ([`06dc3a9`](https://github.com/InnerOpen/marvin/commit/06dc3a91d41668f270eab7c4164c139df0cb784d))

- **automation**: List indexes in template paths; entry metadata in the workflow context
  ([`46d688b`](https://github.com/InnerOpen/marvin/commit/46d688be5d6f8f04369260b2715f0efa34ed3137))

- **automation**: Set_data entry step — write an entry's schema fields from a workflow
  ([`78744ba`](https://github.com/InnerOpen/marvin/commit/78744bac9060027579925c606c4ff976689f7b3b))

- **blueprints**: Entry_fields, incoming_webhook and workflow kinds; applying needs admin
  ([`1cce300`](https://github.com/InnerOpen/marvin/commit/1cce3001817d8ad6b4eab90509c9715456781446))

- **hooks**: Signature schemes for incoming webhooks — Square
  ([`024410d`](https://github.com/InnerOpen/marvin/commit/024410dd6db4d62085d9f41ab726f7a0082ac83a))

- **integrations**: Put and delete on the provider HTTP helper
  ([`aa878a6`](https://github.com/InnerOpen/marvin/commit/aa878a6e15bd54566cb2bd94d4adf16cd55f590e))


## v1.0.0-rc.110 (2026-10-01)

### Bug Fixes

- **ai**: Price the GPT-5 family; an unpriced model costs "unknown", not "Free"
  ([`90cd72a`](https://github.com/InnerOpen/marvin/commit/90cd72a686a25cd894e87967f713f4bcda1f9dae))


## v1.0.0-rc.109 (2026-10-01)

### Bug Fixes

- **ai**: OpenAI reasoning models — no null max_tokens, max_completion_tokens, default temperature
  ([`041c4de`](https://github.com/InnerOpen/marvin/commit/041c4de5239722007cdc8f07fd53f0fd21d65e4a))

- **members**: Invited roles stick, inviting follows the workspace role, user edits save
  ([`a76aab9`](https://github.com/InnerOpen/marvin/commit/a76aab97c4630146335d2a9f2d34dc04c1d48d5e))


## v1.0.0-rc.108 (2026-10-01)

### Features

- **agents**: Workspace inventory + forgiving workflow lookup
  ([`326b831`](https://github.com/InnerOpen/marvin/commit/326b8319ff4d8a72350df47514e043b5cd71d867))


## v1.0.0-rc.107 (2026-10-01)

### Features

- **agents**: Ask-first approval — park a run on its thread, resume with the user's decisions (slice
  C)
  ([`7d63527`](https://github.com/InnerOpen/marvin/commit/7d63527ba480f893ff18dd846d82cdf13ca8da33))


## v1.0.0-rc.106 (2026-10-01)

### Code Style

- **ask**: Links inside answers look like links
  ([`28fe069`](https://github.com/InnerOpen/marvin/commit/28fe0691882a2497473b30104e3fd0bd73950446))

### Features

- **ai**: Executions spawned inside an agent run carry parent_execution_id
  ([`08b244f`](https://github.com/InnerOpen/marvin/commit/08b244f148d94f0f138c85f05df8658bcd21aa53))


## v1.0.0-rc.105 (2026-10-01)

### Bug Fixes

- **sidebar**: Inbox badge on the Entries row, correct counts path
  ([`6e43f26`](https://github.com/InnerOpen/marvin/commit/6e43f26eeada6cef6c49ef24077fb1585e4ccc54))


## v1.0.0-rc.104 (2026-10-01)

### Bug Fixes

- **authoring**: Deterministic review links — absolute when FRONTEND_URL is configured, plus a
  copy-ready reviewLink
  ([`a837ba2`](https://github.com/InnerOpen/marvin/commit/a837ba2b600e56b94983ee164e5dc9ac2dc98b53))


## v1.0.0-rc.103 (2026-10-01)

### Features

- **sidebar**: Inbox row with an unread-style count badge
  ([`b359b7a`](https://github.com/InnerOpen/marvin/commit/b359b7a51a8ec35da01a2c39bd3aa591bffc59c4))


## v1.0.0-rc.102 (2026-10-01)

### Bug Fixes

- **agents**: Keep workspace links relative; ask the specialist for text before an action only
  Marvin can do
  ([`0bdb790`](https://github.com/InnerOpen/marvin/commit/0bdb79005359b6a1802b2980524b76c1c185cbee))


## v1.0.0-rc.101 (2026-10-01)

### Bug Fixes

- **agents**: "auto" from the caller no longer overrides a named agent's own register
  ([`2155bb6`](https://github.com/InnerOpen/marvin/commit/2155bb6e6056c3d53dab1fb833f81b77c571e018))

### Chores

- **tasks**: Slice D verified live
  ([`ddf4e32`](https://github.com/InnerOpen/marvin/commit/ddf4e32e97d972d9e899070c4b4d76058a515aab))


## v1.0.0-rc.100 (2026-10-01)

### Bug Fixes

- **agents**: Make the router hand off on an explicit voice/agent request; lenient find_entries type
  slug
  ([`fc4c1ae`](https://github.com/InnerOpen/marvin/commit/fc4c1ae479229b11600c077af12aa532b6b9b881))


## v1.0.0-rc.99 (2026-10-01)

### Chores

- **tasks**: Slice D rolled out; live verification left for Jared
  ([`1db427c`](https://github.com/InnerOpen/marvin/commit/1db427c317526554e41b5b1c45fa87e229e0a05f))

### Features

- **agents**: Let the system Ask agent refer with suggest_agent
  ([`b178b8c`](https://github.com/InnerOpen/marvin/commit/b178b8c42fbf4b11fe6e1d679e50c0001429b87d))


## v1.0.0-rc.98 (2026-10-01)

### Features

- **agents**: Marvin as router — hand-offs and referrals (v2 slice D)
  ([`2320057`](https://github.com/InnerOpen/marvin/commit/2320057f76b99f87d65be15e9e2be51471e62608))

### Testing

- **agents**: "ask" is a valid tool policy now that POLICY_ASK exists
  ([`27d3f8b`](https://github.com/InnerOpen/marvin/commit/27d3f8b5cc92ebaadae5b5fe74026a0fbd85fac8))


## v1.0.0-rc.97 (2026-09-25)

### Features

- **scheduled-tasks**: Ship the execution-log prune as a system task
  ([`ce6b4c5`](https://github.com/InnerOpen/marvin/commit/ce6b4c5f406696ec639799dff5b6f1318fc5764b))


## v1.0.0-rc.96 (2026-09-25)

### Features

- **scheduled-tasks**: Stop routine no-op runs from burying the execution log
  ([`c34e516`](https://github.com/InnerOpen/marvin/commit/c34e516f8668c45deba1fe699dbfd34cd6e28389))


## v1.0.0-rc.95 (2026-09-25)

### Bug Fixes

- **blueprints**: Catalog test counted whatever providers were installed
  ([`eebd164`](https://github.com/InnerOpen/marvin/commit/eebd164683e6e27dc68f31b5d82dc7d6ebccf1c2))


## v1.0.0-rc.94 (2026-09-25)

### Features

- **integrations**: Show what each integration can actually do
  ([`3e1603b`](https://github.com/InnerOpen/marvin/commit/3e1603b4ab43f0f1fa8ffbd39785869bf90e3aac))


## v1.0.0-rc.93 (2026-09-25)

### Features

- **integrations**: Separate what an integration needs from what it suggests
  ([`bfad431`](https://github.com/InnerOpen/marvin/commit/bfad4311312dcb9a66556c0d4391566d167a2598))


## v1.0.0-rc.92 (2026-09-25)

### Features

- **integrations**: Event-subscription blueprints, and an optional provider icon
  ([`847631d`](https://github.com/InnerOpen/marvin/commit/847631de490f01f0b29545b0c735fae7a01af47a))


## v1.0.0-rc.91 (2026-09-25)

### Bug Fixes

- **integrations**: Deterministic rule order, and document the content declaration
  ([`2c581d2`](https://github.com/InnerOpen/marvin/commit/2c581d2cb6694baca0e036e4b486c561e3cfcb70))


## v1.0.0-rc.90 (2026-09-25)

### Features

- **integrations**: Show what an integration needs to work, and apply it there
  ([`4f8d30e`](https://github.com/InnerOpen/marvin/commit/4f8d30e3f6b965fce710fbe9ef93fde9d63438b2))

### Refactoring

- **blueprints**: No gallery — the catalog belongs where it is useful
  ([`3ec7d61`](https://github.com/InnerOpen/marvin/commit/3ec7d61cc42e838ab2f76b19aba0cc0a3d64c0be))


## v1.0.0-rc.89 (2026-09-25)

### Bug Fixes

- **blueprints**: Drop the core 'drafts' blueprint — it duplicates a system collection
  ([`8a4e923`](https://github.com/InnerOpen/marvin/commit/8a4e923805ef9a6d9da3f67d48c9ed3f750cd978))


## v1.0.0-rc.88 (2026-09-25)

### Features

- **blueprints**: Browse-and-apply page
  ([`cbc15e6`](https://github.com/InnerOpen/marvin/commit/cbc15e69f3b0607d9f15620b48f994d19b672167))


## v1.0.0-rc.87 (2026-09-25)

### Features

- **blueprints**: Ingest provider-declared content; retire the Instagram seed script
  ([`2b71a0c`](https://github.com/InnerOpen/marvin/commit/2b71a0c81d9bf37fa2797a2e55d8fee22bfe7e74))


## v1.0.0-rc.86 (2026-09-25)

### Features

- **blueprints**: Parameters, and a core catalog that names nobody's content
  ([`ed9216c`](https://github.com/InnerOpen/marvin/commit/ed9216c9e43558d12981b2a3fc9e2e6926e5d753))


## v1.0.0-rc.85 (2026-09-25)

### Features

- **blueprints**: Workspace API for browsing and applying blueprints
  ([`6167962`](https://github.com/InnerOpen/marvin/commit/6167962c504ea846ff44f6dcf319dfa0fd0039f8))


## v1.0.0-rc.84 (2026-09-25)

### Features

- **blueprints**: Schema, core catalog and apply semantics
  ([`ce64fe0`](https://github.com/InnerOpen/marvin/commit/ce64fe04f55ab2f4e9312f75dafa20c920a7895a))


## v1.0.0-rc.83 (2026-09-25)

### Bug Fixes

- **workspace**: Stop shipping a 'Recent' collection with every workspace
  ([`921047a`](https://github.com/InnerOpen/marvin/commit/921047ade3791e21cc424b025bbb4b6342533573))


## v1.0.0-rc.82 (2026-09-25)

### Features

- **collections**: Rolling date windows in smart rules; make the Recent default work
  ([`142eb6e`](https://github.com/InnerOpen/marvin/commit/142eb6e9c2cb615e5c901f87af1a2086c306b8ab))


## v1.0.0-rc.81 (2026-09-24)

### Bug Fixes

- **integrations**: Emoji icons and a colour for the IG types and collections
  ([`8a8d183`](https://github.com/InnerOpen/marvin/commit/8a8d183634ad9e50e04131821cb87295a0fe5fb5))


## v1.0.0-rc.80 (2026-09-24)

### Features

- **integrations**: Smart collections for IG rules and sent replies
  ([`53f896f`](https://github.com/InnerOpen/marvin/commit/53f896fb2452cfb464938545a29c9fa239eca7b8))


## v1.0.0-rc.79 (2026-09-24)

### Bug Fixes

- **integrations**: IG reply log entries are published, titled by commenter
  ([`71c65ad`](https://github.com/InnerOpen/marvin/commit/71c65adcac995daefc6298db0b79ecd435e569b4))


## v1.0.0-rc.78 (2026-09-24)

### Features

- **integrations**: Run_integration_action scheduled task + Instagram auto-reply seed
  ([`49490df`](https://github.com/InnerOpen/marvin/commit/49490df8a6fd04727d3b6a90a67436c4cb12307a))


## v1.0.0-rc.77 (2026-09-14)

### Features

- **ai**: Live agent steps — run progress polled while the run is in flight (agents v2, slice B)
  ([`4cafa46`](https://github.com/InnerOpen/marvin/commit/4cafa46619da91993be2ddec52ec6fbf14e6d171))


## v1.0.0-rc.76 (2026-09-14)

### Features

- **ai**: Ask threads — server-side agent conversations (agents v2, slice A)
  ([`49d1aae`](https://github.com/InnerOpen/marvin/commit/49d1aae1d26407a5feb5bf47d4dd6fbf77c1577f))


## v1.0.0-rc.75 (2026-09-13)

### Features

- **ai**: MCP tools placed by their own hints — read / write / destructive rows
  ([`8929438`](https://github.com/InnerOpen/marvin/commit/8929438cdd36a6f5b0ad80569676e1196cb7e327))


## v1.0.0-rc.74 (2026-09-13)

### Bug Fixes

- **ai**: Agents act instead of promising; preamble lists MCP servers; Ask in sidebar
  ([`699540f`](https://github.com/InnerOpen/marvin/commit/699540fd756494f7beda88408e036103898200f2))


## v1.0.0-rc.73 (2026-09-13)

### Features

- **ai**: Agents know what "the RAG" is + workspace_overview tool
  ([`7ab55c2`](https://github.com/InnerOpen/marvin/commit/7ab55c2d37df6eff59cd5c0cb03101295ab569d4))


## v1.0.0-rc.72 (2026-09-13)

### Features

- **ai**: Read-only view_image tool + sticky attachments in Ask
  ([`5e83570`](https://github.com/InnerOpen/marvin/commit/5e8357096e2dbe30595f5e04f25b6e15361d12ea))


## v1.0.0-rc.71 (2026-09-13)

### Features

- **ai**: Agent permission matrix + Agents settings page + Ask becomes the agent chat
  ([`de56ba9`](https://github.com/InnerOpen/marvin/commit/de56ba94fd71957ddcdf7900ff6fc2c78c20067a))


## v1.0.0-rc.70 (2026-09-13)

### Features

- **ai**: Workspace agents v1 — definable persona/model agents, run endpoint, bubble picker, MCP
  tools
  ([`75d4410`](https://github.com/InnerOpen/marvin/commit/75d4410f021ccf73bc66c15bb4261cd166ced0b7))


## v1.0.0-rc.69 (2026-09-13)

### Bug Fixes

- **email**: Unresolved template variables no longer mail the unresolved sentinel
  ([`b1c775b`](https://github.com/InnerOpen/marvin/commit/b1c775b0612a8a05c259a26c089c44026b5dd376))


## v1.0.0-rc.68 (2026-09-12)

### Bug Fixes

- **ui**: Entry-type editor no longer drops capabilities.submission on save
  ([`9dac064`](https://github.com/InnerOpen/marvin/commit/9dac064b0f34a9e723130559e233ca2826e98ac4))


## v1.0.0-rc.67 (2026-09-12)

### Bug Fixes

- **ui**: Browser fetches in email/webhook pages bypassed the session proxy
  ([`9dde843`](https://github.com/InnerOpen/marvin/commit/9dde8434a48c7cf3e95b02590508331c7b722dad))

### Features

- **forms**: Submission protection — platform defaults with per-workspace overrides
  ([`050277b`](https://github.com/InnerOpen/marvin/commit/050277b4094944d7ac32a3e0d68c3583c4b32bac))


## v1.0.0-rc.66 (2026-09-12)

### Bug Fixes

- **ui**: Update banner respected hidden only in theory
  ([`ff9051f`](https://github.com/InnerOpen/marvin/commit/ff9051fd620f023febead6077a1c442cc9b2eae5))


## v1.0.0-rc.65 (2026-09-12)

### Features

- **app**: Public /api/app/about/version for the admin update banner
  ([`76aec4e`](https://github.com/InnerOpen/marvin/commit/76aec4ef21fb0605ceaf9859a76763a3628b89b1))


## v1.0.0-rc.64 (2026-09-12)

### Features

- **ui**: "new version available" banner in the admin
  ([`7666f53`](https://github.com/InnerOpen/marvin/commit/7666f53fef446796673c47ccc1a70829781ba2d1))


## v1.0.0-rc.63 (2026-09-12)

### Bug Fixes

- **ui**: Workflow builder keeps what it cannot edit, and edits the new step fields
  ([`57956e7`](https://github.com/InnerOpen/marvin/commit/57956e7162922f6f07f281d2ef4b2218cdc1c3d1))

### Features

- **webhooks**: A "workflow" webhook type, and delivery logs for workflow steps
  ([`680997a`](https://github.com/InnerOpen/marvin/commit/680997a7225a12973fcd4615ee01425780176cb3))


## v1.0.0-rc.62 (2026-09-11)

### Bug Fixes

- **publish**: Never serve entries of non-publishable types
  ([`0e676a2`](https://github.com/InnerOpen/marvin/commit/0e676a230a50c50c4527b6adc4208b894416f939))


## v1.0.0-rc.61 (2026-09-11)

### Features

- **automations**: Webhook step — method on raw urls, templates in stored urls
  ([`b88e403`](https://github.com/InnerOpen/marvin/commit/b88e4035a6f91fabf3146151ed3ea9d03284b5c9))


## v1.0.0-rc.60 (2026-09-11)

### Features

- **automations**: Entity_query on the entry step
  ([`65ffb64`](https://github.com/InnerOpen/marvin/commit/65ffb648e66d06383bcbc70f1d53fb99989baf1f))


## v1.0.0-rc.59 (2026-09-11)

### Features

- **automations**: Record external ids on entries and target by metadata
  ([`1380e92`](https://github.com/InnerOpen/marvin/commit/1380e92e6b4500b29d5a26eb81f00faac89303a8))


## v1.0.0-rc.58 (2026-09-11)

### Features

- **hooks**: Log the key structure of an incoming payload (keys only)
  ([`4223e10`](https://github.com/InnerOpen/marvin/commit/4223e107ce6e86b96098e0a8acf94f02a184f435))


## v1.0.0-rc.57 (2026-09-11)

### Bug Fixes

- **hooks**: Log the shape of a rejected webhook signature
  ([`41f9f98`](https://github.com/InnerOpen/marvin/commit/41f9f98a204bcc1c8ae4389531c751bc7d6f3a77))


## v1.0.0-rc.56 (2026-09-11)

### Chores

- **chart**: Pin iwobble publicApiUrl to the tunnel host
  ([`2321d42`](https://github.com/InnerOpen/marvin/commit/2321d4243d38ca2153c6a8868d9e2d748d760667))

- **ui**: Vendor-neutral placeholders on the incoming-webhook signing fields
  ([`5d5913f`](https://github.com/InnerOpen/marvin/commit/5d5913fa9c7107de3505af3184c39baea69f3fd6))

### Features

- **ui**: Edit incoming-webhook signing on the card
  ([`ccbf5ca`](https://github.com/InnerOpen/marvin/commit/ccbf5caaa6e34954b974b970d2a98d10f0f949fe))

- **ui**: Generate an incoming-webhook signing key (stored as a secret, shown once)
  ([`d5bbc5d`](https://github.com/InnerOpen/marvin/commit/d5bbc5d78821ff5f5e6aad9061de4c2ea453f008))


## v1.0.0-rc.55 (2026-09-11)

### Features

- **hooks**: Optional HMAC signature verification for incoming webhooks
  ([`a275465`](https://github.com/InnerOpen/marvin/commit/a2754652c396a605e9dad3f18c334a6087d27cb2))


## v1.0.0-rc.54 (2026-09-11)

### Bug Fixes

- **automations**: A non-2xx webhook response fails the step
  ([`fa4f72f`](https://github.com/InnerOpen/marvin/commit/fa4f72f69cc9a4f3c1a79ad130bf4861f47975d6))


## v1.0.0-rc.53 (2026-09-11)

### Bug Fixes

- **automations**: Resolve {{SECRET}} refs in configured webhook headers
  ([`6935bb3`](https://github.com/InnerOpen/marvin/commit/6935bb34f25c2b58a5e77a90d33a00c6a5b1d0e8))


## v1.0.0-rc.52 (2026-09-11)

### Bug Fixes

- **automations**: Entry context tolerates partial entry objects
  ([`c1821a3`](https://github.com/InnerOpen/marvin/commit/c1821a3506bf8a48a2c8034faf9af7703739e175))

### Features

- **automations**: Entry context carries summary and schema fields
  ([`433e949`](https://github.com/InnerOpen/marvin/commit/433e949e4d8280a8905df40723b803971d8d3c8f))


## v1.0.0-rc.51 (2026-09-11)

### Features

- **automations**: Form_submission_received can trigger an automation
  ([`8f1443d`](https://github.com/InnerOpen/marvin/commit/8f1443d14a9adaa2481c624d2370c75a9fe8c89a))


## v1.0.0-rc.50 (2026-09-11)

### Features

- **automations**: Auth_scheme on the webhook action (Token, not only Bearer)
  ([`a65ba7d`](https://github.com/InnerOpen/marvin/commit/a65ba7d0e065097a31d389db0bc3035904d440bb))


## v1.0.0-rc.49 (2026-09-11)

### Bug Fixes

- **deps**: Httpx is a runtime dependency, not an optional extra
  ([`90fb7af`](https://github.com/InnerOpen/marvin/commit/90fb7afffc55fd60892d59261250766870429ef4))

### Chores

- **chart**: Relax the iwobble backend liveness probe
  ([`7271c1b`](https://github.com/InnerOpen/marvin/commit/7271c1b0b51fadb45bfaac9a7e7a6b7a7bc06988))


## v1.0.0-rc.48 (2026-09-11)

### Features

- **publish**: Carry entry data and description on list items
  ([`fadb3f5`](https://github.com/InnerOpen/marvin/commit/fadb3f5220cbc6971bfcd723920e50385bd18441))


## v1.0.0-rc.47 (2026-09-04)

### Bug Fixes

- **ai**: Agent 500 — run_agent read body.register (renamed to tone_register)
  ([`4de61e5`](https://github.com/InnerOpen/marvin/commit/4de61e5aff6a0e66bd806cb7af2fa3a6eadf4632))


## v1.0.0-rc.46 (2026-09-01)

### Bug Fixes

- **media**: Preserve transparency in crop/grade (was flattening onto black)
  ([`bc21db3`](https://github.com/InnerOpen/marvin/commit/bc21db31a623e013aa61dfad52b3d0d3acff3ce7))


## v1.0.0-rc.45 (2026-09-01)

### Features

- **forms**: Rate limiting + CAPTCHA on the entry-type submit path (Phase 1b)
  ([`0fdc23e`](https://github.com/InnerOpen/marvin/commit/0fdc23e28fd00e84adf2984c22c228186fb49be5))


## v1.0.0-rc.44 (2026-09-01)

### Features

- **forms**: Serve submittable entry-type schema from the publishing GET
  ([`f189cce`](https://github.com/InnerOpen/marvin/commit/f189cced0562d05f9178286d130cf60e88303aa6))


## v1.0.0-rc.43 (2026-09-01)

### Bug Fixes

- **events**: Form_submission_received is no longer a dead event
  ([`6e30d18`](https://github.com/InnerOpen/marvin/commit/6e30d1832141c3cf500927cd268680e114fd1587))


## v1.0.0-rc.42 (2026-09-01)

### Features

- **forms**: Route public submits to submittable entry types (forms → entries)
  ([`c192c6c`](https://github.com/InnerOpen/marvin/commit/c192c6c1e722bf403af842b1fcae253e173706d7))


## v1.0.0-rc.41 (2026-09-01)

### Bug Fixes

- **forms**: Read FormRead schema from the ORM's schema_json attribute
  ([`901e8e2`](https://github.com/InnerOpen/marvin/commit/901e8e2b170cc16b08a7bccac75c6f99674bd78f))

### Chores

- **deploy**: Pin iwobble asset URL env + commit cloudflared connector
  ([`57146ad`](https://github.com/InnerOpen/marvin/commit/57146ad6fe2341a62752afb44eb85a73253de3ad))

### Features

- **forms**: Emit form_submission_received on public form submit
  ([`a5a8de2`](https://github.com/InnerOpen/marvin/commit/a5a8de2ea845e53304b15ba1703a495f810b456c))


## v1.0.0-rc.40 (2026-08-31)

### Chores

- Remove committed .mcp.json
  ([`b907103`](https://github.com/InnerOpen/marvin/commit/b9071038d11eecfaa5236840dd6b91541dfefe01))

### Features

- **storage**: STORAGE_LOCAL_PUBLIC_BASE_URL for absolute local-asset URLs
  ([`7a800ca`](https://github.com/InnerOpen/marvin/commit/7a800ca014b49faa4682a1230d9da314020f988f))


## v1.0.0-rc.39 (2026-07-30)

### Bug Fixes

- **ai**: Add missing tone_register field to AIComposeEntryRequest
  ([`f5a9e26`](https://github.com/InnerOpen/marvin/commit/f5a9e2644238705c794aac3abbdc80f5e7c68d1c))

### Chores

- **chart**: Wire OpenAI key into k8s via marvin-ai secret reference
  ([`ad48f4f`](https://github.com/InnerOpen/marvin/commit/ad48f4fbd3995970b1b5cc0a11d3d7d42b68f6b5))


## v1.0.0-rc.38 (2026-07-30)

### Features

- **frontend**: Route browser API calls through a same-origin proxy
  ([`2bc7bb8`](https://github.com/InnerOpen/marvin/commit/2bc7bb8705b2604cb0c8144dd6ae1c7328a12bc1))


## v1.0.0-rc.37 (2026-07-30)

### Bug Fixes

- **frontend**: Add missing scheduled-tasks admin proxy routes
  ([`39c7d1e`](https://github.com/InnerOpen/marvin/commit/39c7d1ed66e0a73127e93511520fbdbaaad3d844))


## v1.0.0-rc.36 (2026-07-30)

### Bug Fixes

- Honor AUTH_COOKIE_NAME setting on the frontend (and backend logout)
  ([`4fcf05a`](https://github.com/InnerOpen/marvin/commit/4fcf05a35cf7b4a9936c5632f8e75470ef9a142d))


## v1.0.0-rc.35 (2026-07-30)

### Bug Fixes

- **frontend**: Make auth cookie Secure flag runtime-configurable
  ([`aa86f3f`](https://github.com/InnerOpen/marvin/commit/aa86f3f6db7b62af8bbe71b81d8835c8db7bb830))


## v1.0.0-rc.34 (2026-07-30)

### Bug Fixes

- **chart**: Set corsOrigins in values-k8s for cross-port NodePort UI
  ([`50fcded`](https://github.com/InnerOpen/marvin/commit/50fcdedd20a5463f926ab4b0be257ee874d15396))


## v1.0.0-rc.33 (2026-07-29)

### Features

- **api**: Enable production CORS for split UI/API deployments
  ([`43b9a53`](https://github.com/InnerOpen/marvin/commit/43b9a5381c7419f5e00ea39a75817084c74065a7))


## v1.0.0-rc.32 (2026-07-29)

### Documentation

- **chart**: Add values-k8s.yaml for plain-Kubernetes deploys
  ([`ce7bd79`](https://github.com/InnerOpen/marvin/commit/ce7bd7928fee6d0a578d834dadc0de1c44a4d4f4))

### Features

- **chart**: Support pinning Service NodePorts
  ([`1ae6f34`](https://github.com/InnerOpen/marvin/commit/1ae6f34ed8e52d1462acdb56385a91fec0af662f))


## v1.0.0-rc.31 (2026-07-28)

### Performance Improvements

- **logs**: Silence health-probe access-log noise
  ([`7b3e38e`](https://github.com/InnerOpen/marvin/commit/7b3e38e63d665357661c7622ebb2ee65bed60e13))


## v1.0.0-rc.30 (2026-07-28)

### Continuous Integration

- Add runner smoke test to verify in-cluster ARC runners
  ([`b251d0f`](https://github.com/InnerOpen/marvin/commit/b251d0feb495f662c4613f87304270708d011954))

- Remove runner smoke test
  ([`56880d4`](https://github.com/InnerOpen/marvin/commit/56880d4fa8b4e4d1d0c977cb5005edf4c40d537c))

- **deploy**: Add manual OpenShift redeploy workflow
  ([`bda2f86`](https://github.com/InnerOpen/marvin/commit/bda2f8680f7bbef11639055afa3f8081d3588372))

### Features

- **helm**: Add iwobble deployment values (split + NFS + plugins)
  ([`a50da5e`](https://github.com/InnerOpen/marvin/commit/a50da5ee3ead9fc6d80e147d8c0120a614665b9a))


## v1.0.0-rc.29 (2026-07-27)

### Bug Fixes

- **frontend**: Honor X-Forwarded-Proto so checkOrigin works behind a TLS proxy
  ([`528d1af`](https://github.com/InnerOpen/marvin/commit/528d1af088892444522a2b51c7ff0163ac9f29b0))

### Features

- **helm**: Split UI/API into separate routes, API internal by default
  ([`073054e`](https://github.com/InnerOpen/marvin/commit/073054e5a40447c40e6e176a299f45b66413a71b))


## v1.0.0-rc.28 (2026-07-26)

### Bug Fixes

- **events**: Allow system-scoped events in the audit log
  ([`bca8a09`](https://github.com/InnerOpen/marvin/commit/bca8a096ccd8569f602a591b3c0af23c429c1f81))

### Features

- **events**: Emit secret_* and variable_* CRUD events
  ([`07337cf`](https://github.com/InnerOpen/marvin/commit/07337cf0a9aa6679ba46ec0a0c79e4c9998ee44f))

- **events**: Migrate event notifiers to apprise integrations (additive)
  ([`e95ace6`](https://github.com/InnerOpen/marvin/commit/e95ace6fc7ed8c3e226c943bdeff9ec9517e3621))


## v1.0.0-rc.27 (2026-07-25)

### Features

- **backup**: Include variables, AI settings, and secrets with a per-workspace key
  ([`eb24c5f`](https://github.com/InnerOpen/marvin/commit/eb24c5fded7ee36a05955322b9e16740a48ae89b))

- **backup**: Include workspace connections & config in export/import
  ([`74e94b3`](https://github.com/InnerOpen/marvin/commit/74e94b30d2a5bddd68574f674347e7a15161c40b))

### Refactoring

- **smtp**: Store the SMTP password in the secret backend via secret_ref
  ([`003f177`](https://github.com/InnerOpen/marvin/commit/003f177d7b3dade08050e34cb53e503f914e2264))


## v1.0.0-rc.26 (2026-07-25)

### Bug Fixes

- **backup**: Skip Marvin-managed collections on restore
  ([`dfdfdfb`](https://github.com/InnerOpen/marvin/commit/dfdfdfb2c8212c124846834e4520da4c7226386e))


## v1.0.0-rc.25 (2026-07-25)

### Bug Fixes

- **frontend**: Pin marvin-sdk to next.28 so the built image has the tags module
  ([`82dcb3e`](https://github.com/InnerOpen/marvin/commit/82dcb3e1355f6cb09eab2e82b2b144b048e613b6))


## v1.0.0-rc.24 (2026-07-25)

### Features

- **scheduler**: Make the tick interval a setting and wire the chart's schedulerInterval
  ([`b6f453b`](https://github.com/InnerOpen/marvin/commit/b6f453b6d812eb20d9b95b737ad74c5a7bc58586))


## v1.0.0-rc.23 (2026-07-25)

### Features

- **scheduler**: Make the leadership lease TTL a setting
  ([`fe88ffe`](https://github.com/InnerOpen/marvin/commit/fe88ffeb344d90616ad297be53f6f367cfabfaa1))


## v1.0.0-rc.22 (2026-07-25)

### Features

- **frontend**: Serve stored media through the frontend
  ([`8fc71da`](https://github.com/InnerOpen/marvin/commit/8fc71da996194e3ce7047902cfd8827b01db4407))


## v1.0.0-rc.21 (2026-07-25)

### Features

- **docker**: Build separate backend and frontend images alongside the combined one
  ([`0f55896`](https://github.com/InnerOpen/marvin/commit/0f55896be67dc8a3cb735468ff14ba17e7bc8386))

- **helm**: Add combined | split deployment mode
  ([`5230b96`](https://github.com/InnerOpen/marvin/commit/5230b96daf34235299dfd1a9d44a285f6f80a1bd))


## v1.0.0-rc.20 (2026-07-25)

### Bug Fixes

- **webhooks**: Let production read webhooks stored with localhost/private URLs
  ([`edc4cbe`](https://github.com/InnerOpen/marvin/commit/edc4cbe6d9872871a0bab2c587505b120a2883da))


## v1.0.0-rc.19 (2026-07-24)

### Bug Fixes

- **ci**: Lowercase the image name in the release image guard
  ([`284c2a4`](https://github.com/InnerOpen/marvin/commit/284c2a46b4163b743d69e65ea6448ccb3952718c))


## v1.0.0-rc.18 (2026-07-24)

### Bug Fixes

- **ci**: Publish the production image on release, not lambda; guard against it
  ([`ea1dd79`](https://github.com/InnerOpen/marvin/commit/ea1dd79eb49edfec8eb50a133d3279ff8fb02724))

### Refactoring

- **frontend**: Use console.debug for DEV_MODE request tracing
  ([`66bc195`](https://github.com/InnerOpen/marvin/commit/66bc195d9a27f6236d5d92f16c3c7c7c0c34850f))


## v1.0.0-rc.17 (2026-07-24)

### Features

- **frontend**: Resolve the backend URL at runtime, not build time
  ([`9af4254`](https://github.com/InnerOpen/marvin/commit/9af42548a97625ea726606ad8afb252b7816429c))


## v1.0.0-rc.16 (2026-07-24)

### Bug Fixes

- **scheduler**: Elect one leader so replicas stop duplicating scheduled work
  ([`acf9aa5`](https://github.com/InnerOpen/marvin/commit/acf9aa5809070ce14e8bb1d396c683664e6716c7))


## v1.0.0-rc.15 (2026-07-24)

### Bug Fixes

- GET /api/admin/groups returned 500 for any workspace containing a user with no username.
  ([`c0fd3a3`](https://github.com/InnerOpen/marvin/commit/c0fd3a31de5d318c83a3f2f0e2f0f9a9afe196ed))

- **config**: Make the frontend actually bind to the port FRONTEND_URL advertises
  ([`4b4e520`](https://github.com/InnerOpen/marvin/commit/4b4e5201837dbff18929a93df4401c465f406752))

### Features

- **frontend**: Add the platform Create User page
  ([`c0fd3a3`](https://github.com/InnerOpen/marvin/commit/c0fd3a31de5d318c83a3f2f0e2f0f9a9afe196ed))


## v1.0.0-rc.14 (2026-07-24)

### Bug Fixes

- **frontend**: Repair broken links on the workspace dashboard
  ([`b98a56d`](https://github.com/InnerOpen/marvin/commit/b98a56dfcb984d869c449ba220e3aaa4b36a3fd5))

### Continuous Integration

- Pin actions to commit SHAs and move off the Node 20 runtime
  ([`f60f3ed`](https://github.com/InnerOpen/marvin/commit/f60f3ed5a8164818b9ee14629f2f8287febe6804))


## v1.0.0-rc.13 (2026-07-24)

### Bug Fixes

- **ci**: Gate release publishing on semantic-release's own output
  ([`5099132`](https://github.com/InnerOpen/marvin/commit/50991321d04554f6837b3f676805b7393f64b325))

### Continuous Integration

- **release**: Keep uv.lock in sync with the version bump
  ([`13e0147`](https://github.com/InnerOpen/marvin/commit/13e01472d1ae15c272acb1f74511f52e155d9890))


## v1.0.0-rc.12 (2026-07-24)

### Features

- **helm**: Support init containers for installing integration plugins
  ([`82341ec`](https://github.com/InnerOpen/marvin/commit/82341ecdd6ecf9179a35607df7c2c6a9cd5066e3))


## v1.0.0-rc.11 (2026-07-24)

### Bug Fixes

- **frontend**: Redirect instead of 500 on protected pages when logged out
  ([`8f57aa4`](https://github.com/InnerOpen/marvin/commit/8f57aa44144f5d35b057014a668b3e95c165f3d6))

- **helm**: Make the chart actually deploy the app
  ([`281d527`](https://github.com/InnerOpen/marvin/commit/281d5278d6121dd91eae3f06734da60e7a2b2254))


## v1.0.0-rc.10 (2026-07-24)

### Bug Fixes

- **helm**: Point chart probes at the new root health endpoints
  ([`04251e5`](https://github.com/InnerOpen/marvin/commit/04251e56e41d92ef4f99a045286bb14de981233e))


## v1.0.0-rc.9 (2026-07-24)

### Features

- **health**: Add root /healthz, /livez, /health, /readyz probes
  ([`9251b51`](https://github.com/InnerOpen/marvin/commit/9251b51adc75e900d7029991966312232b135f00))


## v1.0.0-rc.8 (2026-07-24)

### Features

- **docker**: Build and serve the frontend alongside the API in one image
  ([`5d3cec9`](https://github.com/InnerOpen/marvin/commit/5d3cec91a0f5585350edf8caa9b4d722e2070bfe))


## v1.0.0-rc.7 (2026-07-24)

### Bug Fixes

- **alembic**: Drop the enum types on downgrade so the schema is reversible
  ([`b524990`](https://github.com/InnerOpen/marvin/commit/b524990bd63e33375b03279324e50a2a2767617d))


## v1.0.0-rc.6 (2026-07-24)

### Bug Fixes

- **admin**: Make force-delete of a workspace actually cascade
  ([`e8998be`](https://github.com/InnerOpen/marvin/commit/e8998be7e3241dd6409a7468933e7bef163873e3))

### Code Style

- **ci**: Use the --json shortcut instead of the long --output json form
  ([`0207545`](https://github.com/InnerOpen/marvin/commit/0207545459bb33b3b594dc477aab86174fe616da))

### Testing

- **ci**: Assert the active workspace from JSON instead of grepping prose
  ([`09b3292`](https://github.com/InnerOpen/marvin/commit/09b329269a1fb350ffeb9d141fa1f2c0c76d8e59))

- **ci**: Cover workspace deletion now that force-delete cascades
  ([`788110a`](https://github.com/InnerOpen/marvin/commit/788110a02e11c26ab52975c48cd42415ca1bebd2))

- **ci**: Exercise workspace selection via `workspace use` / `workspace current`
  ([`47149e3`](https://github.com/InnerOpen/marvin/commit/47149e3673010505de08716949ff9262728c759e))


## v1.0.0-rc.5 (2026-07-24)

### Bug Fixes

- **ci**: Authenticate the CLI e2e run and probe a health endpoint that exists
  ([`07f4c80`](https://github.com/InnerOpen/marvin/commit/07f4c80e605345168b0adc22951cee96bebc2c16))

- **ci**: Rewrite the CLI e2e suite against the CLI's real command surface
  ([`3d13e03`](https://github.com/InnerOpen/marvin/commit/3d13e0308bba9cee5a837dec20b5a074fc12136d))


## v1.0.0-rc.4 (2026-07-24)

### Bug Fixes

- **alembic**: Stop silently dropping every index from autogenerated migrations
  ([`4789dbd`](https://github.com/InnerOpen/marvin/commit/4789dbde631e90470838b566aa0dc70e62c76dd5))

- **docker**: Stop shipping demo seed data and auto-importing it in production
  ([`3d4f056`](https://github.com/InnerOpen/marvin/commit/3d4f0565746e458dd32d3a5806ac2e0f52a88035))

- **models**: Reconcile model index/default declarations with the real schema
  ([`0bb4306`](https://github.com/InnerOpen/marvin/commit/0bb43065370b681f1a4d6122c82bf798eab25f57))

### Chores

- **lock**: Sync uv.lock to the 1.0.0rc3 version bump
  ([`2463309`](https://github.com/InnerOpen/marvin/commit/24633099a1fac66a87fce88c3214dcbd29676dcc))

### Code Style

- Clear the repo-wide ruff backlog and unbreak the CI format gate
  ([`28872ac`](https://github.com/InnerOpen/marvin/commit/28872acc9cee50c6ddcc0c5ec7f9240f62382ea1))

### Refactoring

- **alembic**: Squash 41 migrations into a single baseline
  ([`4038b56`](https://github.com/InnerOpen/marvin/commit/4038b56d1c1099dead735b49b1d9ba637e830f2e))


## v1.0.0-rc.3 (2026-07-24)

### Bug Fixes

- **migrations**: Make the webhook_type enum change reversible on Postgres
  ([#20](https://github.com/InnerOpen/marvin/pull/20),
  [`de14656`](https://github.com/InnerOpen/marvin/commit/de146566f1bfbeae10083e871d3a4bc98d8f0e4c))


## v1.0.0-rc.2 (2026-07-24)

### Bug Fixes

- **changelog**: Add the insertion flag so releases update CHANGELOG.md
  ([#19](https://github.com/InnerOpen/marvin/pull/19),
  [`89d0ea1`](https://github.com/InnerOpen/marvin/commit/89d0ea1c1869e32f0e84db166144df63b25015b4))


## v1.0.0-rc.1 (2026-07-24)

- Initial Release

## [0.2.0] - 2026-07-10

Initial version tracking setup with Python Semantic Release.

### Added
- Semantic versioning automation
- Automated changelog generation
- GitHub Actions release workflow

[0.2.0]: https://github.com/InnerOpen/marvin/releases/tag/v0.2.0
