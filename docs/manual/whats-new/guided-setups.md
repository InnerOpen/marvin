# Guided setups, packages and workers

A **guided setup** is a step-by-step page that walks someone through making something in the workspace, one page at a time: adding a painting to a site, narrating a story, scouting a troupe of actors. It can be left and picked up again, and it shows what is already done. A package brings guided setups with it; nothing in a setup is code.

## Where they are

- **Sidebar → Content → Guided setups** (`/workspace/setups`) lists every setup the workspace has, with a Start button on each. The link is always there; the page says how to get one when there are none.
- **Dashboard → Quick create** and the **New** menu list each installed setup (up to three and four), next to the entry types, so "Add artwork" is one click from anywhere.
- **Dashboard view:** a Simple / Detailed switch at the top of the dashboard. Detailed is the whole page; Simple keeps Waiting on you, Pick up where you left off, Quick create and Recent work, in one column, for someone who only adds and edits. It is remembered in that browser, like light and dark.
- **A button on an entry's page.** A setup can say it belongs to an entry type (`button`: the entry type, a label, the context key the entry fills, optionally the step to open on and fields to carry over, like a line's story). Every entry of that type then shows the button next to its other actions, and it opens the setup with that entry already chosen. Screenplay Studio uses it for **Takes** on a speech line.
- **Reading the thing you are working on.** Any step can carry `show` (`{entry, fields}`): a card above the step with the chosen entry's own words, so someone recording a line sees its text and direction. A `gallery` can be a list (`layout: list`), mark the card whose field has a value (`highlight`, the take in use), name what it makes after its parent (`name: {from, noun}`, "01 Granny: People say… · take 2"), say what happened after one is added (`added`), and keep a sound's length (`upload.seconds`): a recording brings the length its recorder counted, a file from disk is measured in the browser, because Marvin only stores a length for sound it generated. In the timeline, a line with a take but no stored length keeps the text's estimate and is drawn with a dashed edge instead of as "no take yet".
- **A real form for what you make, with its approvals on the page.** A gallery's `add` form can start open (`open`), take a heading (`title`), start from the chosen entry's own values (`prefill`, a take from its line's words, direction and voice: edit them to try something different), hold a Record / Upload box (`file`) and offer up to three buttons (`buttons`: each with its own `data`, and `file` required or none), for example *Save my take* or *Make with ElevenLabs*. A gallery's `approve` lists workflows of the same package whose approvals show above the list and are answered there, so you never leave the page to approve; the page refreshes while something is being made.
- **A timeline lane can open a setup.** A view's lane may say `open: {wizard}`: clicking one of its pieces then opens that guided setup with the piece chosen (a line in Screenplay Studio's timeline opens its takes) instead of the piece's own page. The setup must declare a `button` for that entry type.
- **Remove from a list.** A gallery with `trash: true` puts a *Remove* button on each card. It asks first, then moves that entry to the Trash (restorable from there); only entries the gallery itself lists can be removed this way. Screenplay Studio uses it to drop a take.
- **Settings → Automation → Packages** shows which package brought a setup.

## Getting one

Guided setups arrive in a [package](workflows.md): a `.marvin-package.json` file. On **Settings → Automation → Packages**, **Add a package** takes the file (choose it or drop it), shows exactly what it would create, and installs it on **Install**. Installing again replaces the package's own setup with the new version and leaves everything else alone. **Download** on an installed package gives the file back, to use in another workspace. A package can also be installed with the API (`POST /api/groups/packages/install`, with `/preview` to check first).

## What a setup can do

A setup is a list of steps. The kinds:

| Step | What it does |
|---|---|
| `option` | Picks one of a few labelled values, only to branch on (`when` shows a later step only for a choice). |
| `choose` | Picks an entry of a type, or makes a new one. With `picture` (and `subtitle`) the choices are picture tiles; a list longer than eight gets a **search box** that filters as you type, and **"make a new one" moves above it** so it is not lost. With `create.upload` the new one starts from a **file**: upload a picture, and the entry is made from it, named for what you typed or for the file. |
| `form` | Edits some fields of an entry chosen earlier. |
| `upload` | A file for an entry's field. Shows the picture as it is now, and asks before replacing one. |
| `list` | The entries that belong to another (a story's characters), editable in place, with a way to add one. |
| `gallery` | Entries as picture cards with a play button for sound; upload a picture or sound to make a new entry, or start a generation. |
| `run` | A button that starts a workflow the same package brings, such as bringing in a screenplay. The step then says where that run stands, as it goes: *Starting*, *Running (3 of 7 steps done)*, *Waiting on you* (its question is on the page), *Working* (the worker job it started), *Done* (Continue becomes the main button) or *Failed* (with the reason, and Run again). A gallery's Generate button says the same. The address carries the run (`run=<id>`), so the line survives a reload; `run`, like `step` and `notice`, cannot be a step's `as`. Before the button, the step lists **what the run will work on**: when the workflow starts by gathering entries (a `collect` step), the step runs that same step with the same inputs, reading only, and shows the entries it would get (title, a play button for a sound field named in `audio`, up to two `badges`, a `subtitle`), with how many (*the next 30 of 45* when the workflow takes 30 at a time). The list is the workflow's own, so the page and the workflow cannot disagree; a package declares nothing twice. The button may count them (`"button": "Make these ${count} sounds"`). `left_out` (up to four `{label, where}`) gives the package's words for what is not in the list (*Not included: 1 music, 3 already have a file*): each `where` is counted over the rest of the workflow's query. With nothing in the list the step says so (`empty`, or a plain default) and Continue becomes its button. `report` (`{entry, field, label?}`) shows a field the run writes, such as a check's findings, with a link to edit that entry; a run that ended in a worker job shows what the job said. Every run step but the last has *Next step without running*. Someone who may not start workflows still sees the list, the report and the skip. |
| `review` | Checks (counts of entries, compared to a number) that say what is still missing, each linking back to the step that makes it. |

`${name}` reads a choice made earlier. A setup ends with `next` (what to do after, with links) and `open` (a button that opens what was made, or its view). Field keys may be camelCase (`sellOnline`). A picture field is read under its role, so a type whose `image` field has `role: "featured"` shows the pictures attached as *featured*. The format is validated when the package is previewed; see `services/blueprints/wizards.py` for the exact rules.

## Workers

Some work is too heavy for the web server: cutting audio, rendering a video, converting a recording to mp3, working out a screenplay's chapters. That runs on a **worker**, a separate process that polls the workspace for **job** entries and writes the result back on the job.

- A worker registers the **kinds** of job it can do. A kind declares what it takes, what it gives and what it needs, so a bad job fails at once with the reason on its record.
- A package's workflows create jobs (a `job` entry with a `kind` and `args`); a worker picks them up. The worker image comes from the package's own repository, and which kinds a runner offers is set in its configuration.
- **Settings → Workers** shows which workers are alive, what each kind takes, the queue, and every job's log and result. A worker that is not running shows a grey dot, not a red one.
- Workers only reach out to Marvin; nothing listens. Install the package first (it brings the `job`, `job-kind` and `worker` record types), then run the worker with the workspace's credentials.

Workers matter to whoever runs the workspace's heavy workflows. People who only use a guided setup, such as adding artwork, never see one.
