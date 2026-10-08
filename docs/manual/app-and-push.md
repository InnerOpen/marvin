# The app and push notifications

The admin is an installable web app (a PWA): it can sit on a phone's home screen or a computer's dock and open in its own window, and it can send push notifications to the devices people turn them on for. Nothing to download from a store; it is the same admin, served by the same frontend.

## Installing the app

**Profile → Install the app** shows what this browser offers:

| Where | How |
|---|---|
| Chrome, Edge (desktop), Chrome on Android | **Install app** in Profile runs the browser's own install prompt. The browser's menu (*Install app* / *Add to Home screen*) and Chrome's address-bar install icon work too. |
| Safari on iPhone and iPad | Tap **Share**, then **Add to Home Screen**. Safari has no install prompt for Profile to show, so Profile says this instead. |
| Safari on macOS (Sonoma and later) | **File → Add to Dock**. |
| Firefox | Desktop Firefox doesn't install web apps; Firefox on Android does, from its menu. The admin works in a tab either way. |

Once Marvin runs as the installed app, Profile says so and the install entry goes away. The app opens on the dashboard; its shortcuts (long-press or right-click the icon) go to **Ask**, **New entry** and the **Review queue**. On an installed app the icon shows how many entries wait in the current workspace's inbox (the number on the Entries badge) plus how many of your conversations wait for your approval in any workspace, where the system supports app badges (`GET /api/self/push/badge` gives both parts). An approval's notification and its Approve/Deny confirmation update the count too.

A non-production instance (the backend's `ENVIRONMENT_LABEL`, e.g. `DEV`) installs as **Marvin DEV**, with a dark icon and an amber title bar, so it can't be mistaken for the real one on a home screen.

### Offline and updates

The app keeps only static files on the device: the hashed scripts and styles, the icons and an offline page. Pages and API responses are never stored, so nothing one person saw stays on a shared device for the next, and **logging out empties the app's caches**. The one exception is something you [share to Marvin](#share-to-marvin): it waits on the device until you add it (or for an hour), and logging out empties that too. With no network, opening a page shows "You're offline" and reloads by itself when the connection comes back.

**Uploads that wait for a connection.** An upload from **Assets → New**, or **Add to Assets** on the Share page, that fails because the device is offline or the connection dropped (or the server answered 408, 429 or a 5xx) is kept on the device — the file and what you typed, in the app's `marvin-uploads` cache — and the page says so. A note in the corner of every page counts what waits; the uploads go when the connection comes back or the app next opens (**Send now** tries at once, **Discard** drops them). Each goes to the workspace it was meant for: one queued for another workspace waits, saying so, until that workspace is active. An upload the server refused (too big, a type it doesn't take, no permission, a slug taken) is not kept or retried, since that answer won't change. At most 20 wait at a time. Logging out discards them after asking. **New entry** on the Share page still needs its files uploaded at once, so it doesn't queue.

After a deploy, the new version installs in the background and the bar at the top says **A new version of Marvin is available** — **Reload** switches to it. (The same bar already announced deploys; it now also covers the app's own files.)

## Push notifications

Push is off until the server has VAPID keys (see [Setting up push](#setting-up-push-operators) below). Then **Profile → Notifications** appears:

- **Turn on for this device** asks the browser for permission (only when clicked, never on page load) and registers the device. **Turn off for this device** removes it.
- **Send me** — the kinds of notification you get, on every device:

  | Kind | What sends it | Who can get it |
  |---|---|---|
  | Workspace activity | A form submission (not one flagged as spam) and a scheduled publish that's waiting — what the bell flags for a person | Editors, admins and owners of the workspace; never whoever caused it |
  | AI approvals | An agent run that stopped to ask before it acts ("ask first") | Only the person whose run it is; the notification opens the Ask thread to decide, or has [Approve and Deny](#approve-or-deny-from-the-notification) buttons |
  | Workspace alerts | The **Push** channel of Settings → Automation → Notifications | Owners and admins |
  | Trash reminders | The day before the Trash's auto-empty deletes items forever: "*Workspace*: 14 items will be deleted forever tomorrow", opening the Trash. At most one a day per workspace | Owners and admins |
  | Platform alerts | The **Push** channel of Admin → Platform alerts | Super admins |

- **Send a test** sends one to each of your devices; the list then shows when each was last reached.
- **Devices with notifications on** lists every browser and phone push is on for, with **Remove**.

**Notifications stay on after you log out** — they belong to the device, so you keep getting them without staying signed in. On a shared or borrowed device, turn them off in **Profile** before you hand it back, or remove the device from Profile on any other device later. If someone else turns notifications on in that browser, the device moves to their account.

A notification carries a title, one line and a link into the admin — never a submission's fields, an agent's tool arguments or anything secret. Clicking it focuses an open Marvin window (or opens one) on that page; links only ever lead into the admin itself. A notification about a workspace (an approval, the Trash reminder, new activity, a workspace alert) switches to that workspace first when another one is active, so the page opens where the thing is. The active workspace is yours, not the device's, so this switches it in your other tabs too, as the workspace switcher does; platform alerts open under **Admin** without switching.

### Approve or deny from the notification

When an agent waits only on things you can undo in Marvin — moving to the Trash or restoring from it (an "all of them" `match` included), archiving, attaching or detaching tags, adding to or removing from a collection — its notification has **Approve** and **Deny** buttons. Approve runs exactly what **Approve** on the Ask page would: the agent carries on and its answer is in the conversation when you open it. A confirmation replaces the notification ("Approved — moved 78 entries to the Trash"), and the app icon's count updates. Deny is the Ask page's Deny.

Anything else — publishing, email, a connection's actions, running a workflow, writing or revising an entry, or a hand-off whose specialist would do any of these — gets no buttons: tap the notification and decide in the conversation, where you can see the details. Marvin decides this from the waiting run itself, not from anything in the notification.

The buttons work without being signed in on that device: each notification carries a one-time key for that one approval, for you only, that lasts 15 minutes. It stops working once used, once the approval is decided any other way (on the Ask page, by a new message, by expiring), and when its 15 minutes are up; a few wrong tries for the same approval lock it out for a while. If the button can't decide any more, the notification says why ("This approval was already decided") and opens the conversation. Decisions made this way are recorded like any other, with *push* as where they came from.

Chrome and Edge (desktop and Android) show the buttons. Safari on iPhone, iPad and the Mac, and Firefox, don't show notification buttons: tap the notification to open the conversation, as before.

## Share to Marvin

With Marvin installed, Chrome and Edge on Android and on the desktop list it in the **Share** sheet of other apps. Share photos, videos or PDFs (up to 10 at a time; other kinds are left out and the page says so), or a link or some text, and Marvin opens its **Share** page:

- **Add to** — the workspace it goes to, your current one to start with; **Switch** changes your current workspace and comes back.
- A preview of each file, and the shared title, text and link.
- **Add to assets** uploads every file as an asset, the same as uploading on the Assets page (same roles, size limit, storage and events).
- **New entry with these** uploads the files, then creates a draft of the entry type you pick with them attached: the shared title (or the text's first line) as its title, and the text and link in its body field (a field called body, content or notes, else its first long-text field; with none, in the entry's description).
- **Add as resource (link)** — when a link was shared — adds it as a `link` resource (editors and above, as on the Resources page).
- **Discard** drops the share.

If you aren't signed in, Marvin asks you to sign in first and then shows the share. What you share stays on the device until you press one of the buttons; it is dropped once used and after an hour. Viewers see the share but can't add it.

**iPhone and iPad:** iOS doesn't offer installed web apps in the Share sheet, so Marvin isn't listed there. Nothing else changes: upload on the Assets page as usual.

### The Push channel on the alert pages

Settings → Automation → Notifications and Admin → Platform alerts get a **Push** channel next to Email and the integration routes, when the server has push. It is on by default and goes to the owners and admins (platform alerts: super admins) who turned notifications on with the matching kind in their Profile; the card lists who that is right now. Like the other channels it can take only some kinds (workspace notifications), has its own last delivery and **Send test**, and follows the same rules: one alert per incident while something keeps failing, and the "working again" note goes to the channels the alert went to. Without push configured the pages and their deliveries are exactly as before.

### iPhone and iPad

iOS delivers web push only to an app on the Home Screen, from **iOS 16.4**: add Marvin to the Home Screen, open it from there, then turn notifications on in Profile. In Safari's tab, Profile explains this instead of offering the button.

## Setting up push (operators)

Push needs a VAPID key pair: the public key browsers subscribe with, the private key the backend signs messages with, and a contact (`mailto:` or `https:`) push services can reach.

```bash
uv run python -m marvin.scripts.vapid --subject mailto:ops@example.com
# VAPID_PUBLIC_KEY=B…
# VAPID_PRIVATE_KEY=…
# VAPID_SUBJECT=mailto:ops@example.com
```

Set the three lines in the backend's environment (`.env`, or a Secret). Generate the pair **once per installation** and keep the private key secret: a new pair invalidates every existing subscription, and everyone has to turn notifications on again. The private key is masked in settings output like the other secrets.

On Kubernetes/OpenShift the chart reads them from a Secret it never renders (`webPush.existingSecret`; `values-dev.yaml` and `values-iwobble.yaml` name `marvin-vapid`):

```bash
uv run python -m marvin.scripts.vapid --subject mailto:ops@example.com > vapid.env
oc create secret generic marvin-vapid -n marvin --from-env-file=vapid.env && rm vapid.env
oc rollout restart deployment/marvin-backend -n marvin   # split mode; deployment/marvin when combined — or wait for the next deploy
```

The Secret references are optional, so naming it in the values before it exists is harmless: the backend starts with push off and the admin hides push. Use a separate pair per environment (dev and production are separate installations).

Sending is part of the backend (`pywebpush`), off the request path: event listeners and background tasks post to each device's push service with a 24-hour TTL, one attempt each with a 10-second timeout. A device the push service reports gone (404/410) is deleted; other failures count on the device and show in its Profile entry until it is reached again. In production a subscription must point at a public `https` host. The API is `GET /api/self/push`, `PUT /api/self/push/preferences`, `POST /api/self/push/subscriptions`, `DELETE /api/self/push/subscriptions/{id}` (or `?endpoint=` for this device) and `POST /api/self/push/test`, all limited to the signed-in user's own devices. The notification buttons post to `POST /api/self/push/approvals/{thread id}/approve` (or `/deny`) with `{"token": …}` and no session; only a hash of each token is stored (`push_action_tokens`).

The Trash reminder is checked hourly on the scheduler leader (`remind_trash_auto_empty`): for each workspace whose auto-empty isn't **Never**, the entries, assets and resources due within 24 hours. When there are any it fires `trash_auto_empty_soon` once that day (the day is claimed on `group_preferences.trash_reminded_on`, so another tick or replica sends nothing); the push goes out from that event. The same event is an optional kind on Settings → Automation → Notifications (off by default) for email and connections; the **Push** channel there doesn't take it, since each person chooses that push in their Profile.

Asset uploads (the Assets page, Share to Marvin, the API) now keep to `ASSET_MAX_FILE_SIZE` (100 MB unless set; a bigger file gets 413) and, when set, `ASSET_ALLOWED_MIME_TYPES` (shell-style patterns such as `image/*`, matched against the type detected from the file; anything else gets 415). Both settings existed before but weren't checked.
