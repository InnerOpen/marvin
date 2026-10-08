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

Once Marvin runs as the installed app, Profile says so and the install entry goes away. The app opens on the dashboard; its shortcuts (long-press or right-click the icon) go to **Ask**, **New entry** and the **Review queue**. On an installed app the icon shows how many entries wait in the inbox (the number on the Entries badge), where the system supports app badges.

A non-production instance (the backend's `ENVIRONMENT_LABEL`, e.g. `DEV`) installs as **Marvin DEV**, with a dark icon and an amber title bar, so it can't be mistaken for the real one on a home screen.

### Offline and updates

The app keeps only static files on the device: the hashed scripts and styles, the icons and an offline page. Pages and API responses are never stored, so nothing one person saw stays on a shared device for the next, and **logging out empties the app's caches**. With no network, opening a page shows "You're offline" and reloads by itself when the connection comes back.

After a deploy, the new version installs in the background and the bar at the top says **A new version of Marvin is available** — **Reload** switches to it. (The same bar already announced deploys; it now also covers the app's own files.)

## Push notifications

Push is off until the server has VAPID keys (see [Setting up push](#setting-up-push-operators) below). Then **Profile → Notifications** appears:

- **Turn on for this device** asks the browser for permission (only when clicked, never on page load) and registers the device. **Turn off for this device** removes it.
- **Send me** — the kinds of notification you get, on every device:

  | Kind | What sends it | Who can get it |
  |---|---|---|
  | Workspace activity | A form submission (not one flagged as spam) and a scheduled publish that's waiting — what the bell flags for a person | Editors, admins and owners of the workspace; never whoever caused it |
  | AI approvals | An agent run that stopped to ask before it acts ("ask first") | Only the person whose run it is; the notification opens the Ask thread to decide |
  | Workspace alerts | The **Push** channel of Settings → Automation → Notifications | Owners and admins |
  | Platform alerts | The **Push** channel of Admin → Platform alerts | Super admins |

- **Send a test** sends one to each of your devices; the list then shows when each was last reached.
- **Devices with notifications on** lists every browser and phone push is on for, with **Remove**.

**Notifications stay on after you log out** — they belong to the device, so you keep getting them without staying signed in. On a shared or borrowed device, turn them off in **Profile** before you hand it back, or remove the device from Profile on any other device later. If someone else turns notifications on in that browser, the device moves to their account.

A notification carries a title, one line and a link into the admin — never a submission's fields, an agent's tool arguments or anything secret. Clicking it focuses an open Marvin window (or opens one) on that page; links only ever lead into the admin itself.

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

Sending is part of the backend (`pywebpush`), off the request path: event listeners and background tasks post to each device's push service with a 24-hour TTL, one attempt each with a 10-second timeout. A device the push service reports gone (404/410) is deleted; other failures count on the device and show in its Profile entry until it is reached again. In production a subscription must point at a public `https` host. The API is `GET /api/self/push`, `PUT /api/self/push/preferences`, `POST /api/self/push/subscriptions`, `DELETE /api/self/push/subscriptions/{id}` (or `?endpoint=` for this device) and `POST /api/self/push/test`, all limited to the signed-in user's own devices.
