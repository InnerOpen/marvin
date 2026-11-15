# Guided setups, packages and workers

A **guided setup** is a step-by-step page that walks someone through making something in the workspace, one page at a time: adding a painting to a site, narrating a story, scouting a troupe of actors. It can be left and picked up again, and it shows what is already done. A package brings guided setups with it; nothing in a setup is code.

## Where they are

- **Sidebar → Content → Guided setups** (`/workspace/setups`) lists every setup the workspace has, with a Start button on each. The link is always there; the page says how to get one when there are none.
- **Going round again.** A setup can end with a button that starts it over from a step it names (`again`: `{label, step}`), keeping the choices made before that step and forgetting the rest: "Cast another role" goes back to the role pick with the world and the story still chosen.
- **Opening on a question.** A setup can start with an `option` that every later step waits on (`when`): "One work or several?", with one run of steps for each answer and a `review` at the end of each. Until it is answered the question reads as the first step of more to come: its button says **Continue**, it shows no "of N" (the count depends on the answer) and no go-again button; the steps for the answer appear once it is given. `again` may name the question, to start over from it. The same holds for any choice a later step waits on that has no answer yet.
- **Dashboard → Quick create** and the **New** menu list each installed setup (up to three and four), next to the entry types, so "Add artwork" is one click from anywhere.
- **Dashboard view:** a Simple / Detailed switch at the top of the dashboard. Detailed is the whole page; Simple keeps Waiting on you, Pick up where you left off, Quick create and Recent work, in one column, for someone who only adds and edits. It is remembered in that browser, like light and dark.
- **A button on an entry's page.** A setup can say it belongs to an entry type (`button`: the entry type, a label, the context key the entry fills, optionally the step to open on and fields to carry over, like a line's story). Every entry of that type then shows the button next to its other actions, and it opens the setup with that entry already chosen. Screenplay Studio uses it for **Takes** on a speech line.
- **Reading the thing you are working on.** Any step can carry `show` (`{entry, fields}`): a card above the step with the chosen entry's own words, so someone recording a line sees its text and direction. A `gallery` can be a list (`layout: list`), mark the card whose field has a value (`highlight`, the take in use), name what it makes after its parent (`name: {from, noun}`, "01 Granny: People say… · take 2"), say what happened after one is added (`added`), and keep a sound's length (`upload.seconds`): a recording brings the length its recorder counted, a file from disk is measured in the browser, because Marvin only stores a length for sound it generated. In the timeline, a line with a take but no stored length keeps the text's estimate and is drawn with a dashed edge instead of as "no take yet".
- **A real form for what you make, with its approvals on the page.** A gallery's `add` form can start open (`open`), take a heading (`title`), start from the chosen entry's own values (`prefill`, a take from its line's words, direction and voice: edit them to try something different), hold a Record / Upload box (`file`) and offer up to three buttons (`buttons`: each with its own `data`, and `file` required or none), for example *Save my take* or *Make with ElevenLabs*. A gallery's `approve` lists workflows of the same package whose approvals show above the list and are answered there, so you never leave the page to approve; the page refreshes while something is being made.
- **A timeline lane can open a setup.** A view's lane may say `open: {wizard}`: clicking one of its pieces then opens that guided setup with the piece chosen (a line in Screenplay Studio's timeline opens its takes) instead of the piece's own page. The setup must declare a `button` for that entry type.
- **Remove from a list.** A gallery with `trash: true` puts a *Remove* button on each card. It asks first, then moves that entry to the Trash (restorable from there); only entries the gallery itself lists can be removed this way. Screenplay Studio uses it to drop a take.
- **Settings → Automation → Packages** shows which package brought a setup.

## Getting one

Guided setups arrive in a [package](workflows.md): a `.marvin-package.json` file. On **Settings → Automation → Packages**, **Add a package** takes the file (choose it or drop it), shows exactly what it would create, and installs it on **Install**. Installing again replaces the package's own setup with the new version and leaves everything else alone. A setup the newer file no longer lists goes with it, since a setup lives in the package's file (a package that folds two setups into one leaves the one); workflows, entry types, fields and entries are never removed. **Download** on an installed package gives the file back, to use in another workspace. A package can also be installed with the API (`POST /api/groups/packages/install`, with `/preview` to check first).

## What a setup can do

A setup is a list of steps. The kinds:

| Step | What it does |
|---|---|
| `option` | Picks one of a few labelled values, only to branch on (`when` shows a later step only for a choice). With **`templates`** (an entry type's slug) in place of `options`, the choices are that type's [templates](entry-templates.md) as the workspace has them now, drawn as cards with each one's name and what it is for; the only one there is starts picked, and a type with none says where an admin adds one. The step sets the template's slug, for a run step to hand on. |
| `choose` | Picks an entry of a type, or makes a new one. With `picture` (and `subtitle`) the choices are picture tiles; without one, they are still picture tiles when the type has a picture field (its first single asset field that takes pictures) and the entries have pictures in it, a character with its master, and a plain list otherwise. **`cards: true`** makes them tiles anyway, for a type with no picture (a world, a chapter): each tile shows the first letter of its title. A list longer than eight gets a **search box** that filters as you type, and **"make a new one" moves above it** so it is not lost. With `create.upload` the new one starts from a **file**: upload a picture, and the entry is made from it, named for what you typed or for the file. With **`multiple: true`** it picks several: see *Picking several* below. |
| `form` | Edits some fields of an entry chosen earlier. A file field (one asset, or a list) shows the entry's own asset control: choose one from the workspace, upload, or record. |
| `upload` | A file for an entry's field. Shows the picture as it is now, and asks before replacing one. |
| `list` | The entries that belong to another (a story's characters), editable in place, with a way to add one. **Without a parent** it is a checklist over the entries a `where` finds: see *Checking a list of entries* below. |
| `gallery` | Entries as picture cards with a play button for sound; upload a picture or sound to make a new entry, or start a generation. |
| `run` | A button that starts a workflow the same package brings, such as bringing in a screenplay. The step then says where that run stands, as it goes: *Starting*, *Running (3 of 7 steps done)*, *Waiting on you* (its question is on the page), *Working* (the worker job it started), *Done* (Continue becomes the main button) or *Failed* (with the reason, and Run again). A gallery's Generate button says the same. The address carries the run (`run=<id>`), so the line survives a reload; `run`, like `step` and `notice`, cannot be a step's `as`. Before the button, the step lists **what the run will work on**: when the workflow starts by gathering entries (a `collect` step), the step runs that same step with the same inputs, reading only, and shows the entries it would get (title, a play button for a sound field named in `audio`, up to two `badges`, a `subtitle`), with how many (*the next 30 of 45* when the workflow takes 30 at a time). The list is the workflow's own, so the page and the workflow cannot disagree; a package declares nothing twice. The button may count them (`"button": "Make these ${count} sounds"`). `left_out` (up to four `{label, where}`) gives the package's words for what is not in the list (*Not included: 1 music, 3 already have a file*): each `where` is counted over the rest of the workflow's query. With nothing in the list the step says so (`empty`, or a plain default; see *When a step has nothing to show*) and Continue becomes its button. **A workflow that starts by previewing a template** (a `create_entries_from_template` or `apply_template` step in `mode: preview`, before the one that writes) is listed the same way: the step shows that preview, one card per picture or entry with its picture, the title it will have and the values the template sets, each under its field's name (*New*, *Already there: only what is empty is filled*, or why it is left out). `${count}` is how many it will make or fill. A card with a problem says so, and the button stays off until it is fixed, as it does while a run is going; once the run is done the cards open the entries it made. See *Entries from the pictures picked* below. `report` (`{entry, field, label?}`) shows a field the run writes, such as a check's findings, with a link to edit that entry; a run that ended in a worker job shows what the job said. Every run step but the last can be skipped until it has run. Someone who may not start workflows still sees the list, the report and the skip. |
| `review` | Checks (counts of entries, compared to a number) that say what is still missing, each linking back to the step that makes it. |

### Picking several

A `choose` step with `multiple: true` is a multi-select: the cards get a **checkbox** each (the card toggles it; Tab and Space work), with **Select all on this page**, **Clear** and a live **"12 selected"** line. The cards come a page at a time (50, or `per=25|100` in the address), with Previous and Next under them; **what you tick stays ticked when you change page**, and when you go on to the next step and come back. Continue keeps the picks as **one list** in the setup's context, which rides in the address like every choice: the slugs of the entries (or the ids of the assets) joined with commas, `pictures=6f1c…,a8e2…`. A list holds **at most 100**; past that the step says how many to untick, and nothing is cut in silence. Without a script the buttons still work: each one posts the page, and the server keeps the picks the same way.

- **Cards of entries:** `entry_type` with `scope`, `picture`, `subtitle` and `sort`, as a single pick (a multi-select cannot `create`).
- **Cards of files:** `assets` instead of `entry_type`, with the Assets library's filters: `asset_type`, `tag`, `collection`, `q`, `origin`, `unattached`, and **`unused: true`** for the files no entry uses yet (attached to none, and named by no entry's picture field, which an entry saved before those fields attached their file can still do). `{"assets": {"asset_type": "image", "unused": true}}` is "the pictures that have no artwork yet".
- **Using the list later:** a run step's `inputs` take it as `${pictures}` (comma-separated: an entry query's `entries`, or an asset query's `ids`, reads it), a review check's query the same, and **`selection: "pictures"`** on any later step shows the picks as cards (*The 12 you picked*, with **Change**). A list is never one entry: a scope, `create.data`, `entry`, `parent`, `show` and the like cannot name it, and saying so is an error when the package is checked.
- `page` and `per`, like `step`, `notice` and `run`, cannot be a step's `as`.

### Entries from the pictures picked

Three steps make entries from pictures with a template, and show what will be made first. Grace's **Add artwork from pictures** is one:

1. a `choose` step with `multiple: true` over `assets` (`{"asset_type": "image", "unused": true}`: the pictures no entry uses yet), `as: "pictures"`;
2. an `option` step with `templates: "artwork"`, `as: "template"`;
3. a `run` step with `inputs: {"pictures": "${pictures}", "template": "${template}"}` and a button such as `"Make these ${count} works"`.

The workflow the package brings for it takes the two as inputs (`pictures` as a `textarea`: a hundred ids are longer than a `text` input allows) and has two steps: `create_entries_from_template` with `assets: "${input.pictures}"` and `template: "${input.template}"` (a preview, by default), then the same step with `mode: create` and `confirm_total: "${steps.<the preview's id>.output.todo}"`. The entries arrive as Inbox drafts, titled after their pictures. An `again` button (*Add more pictures*) starts over at the first step.

A template is added to a type the workspace already has by an `entry_type` blueprint that carries only the type's `name` and its `templates_json`: a package **update** adds the templates the type lacks, by slug, and leaves its fields alone. (A plain install leaves an existing type as it is, templates included.)

### Checking a list of entries

A `list` with no `parent` and `parent_field` lists the entries of `entry_type` that meet its `where` (plain conditions, as a collect's: `{field, op, value?}`, where `publish_status` is the entry's own status and a bare key its type's field), plus those that meet `or_where` if it has one. Grace's **Art price check** is one: every published piece that is `available`, or `sold` and still for sale online.

- **Cards, a page at a time** (25, or 50 / 100), each with its picture (`picture`, else the type's picture field), its name (a link to the entry), up to three fields under it (`subtitle`) and the step's `columns` to edit in place. A yes/no column is a switch.
- **`check`** (`{field, label}`): a yes/no field drawn as a button on each card (*Looks right*). Pressed, the card turns green, and the step counts them (*12 of 104 marked "Looks right"*). Pressing it again unticks it, which is how a piece is checked again later.
- **`flags`** (up to 6 `{label, where, attention?}`): the server says which listed entries meet each one, the card shows the label (*No price*), and each is a filter with its count. **Needs attention** is any flag without `attention: false`. With a `check`, **Not checked yet** and **Checked** filter too.
- **`facet`**: a select field whose values filter the cards with their counts (*Ornaments 28*). There is also a **search by name**.
- **`fill`**: columns a box fills on every card shown where they are empty (*the shipping fee on these pieces*). It is saved with the page.
- **Saving.** Nothing is saved while typing. Every button on the step (Save this page, a filter, Search, Next, Continue) saves the cards' changes first, so moving around never loses an edit. A card that was changed and not saved yet is marked, and leaving the page by a link asks first. Each changed card is **one** update with only what changed on it, made one after the other. It is merged into the entry as it is at that moment, so a sale that arrived meanwhile stays. Only entries the step lists, and only its `columns` and `check`, can change; a required field of the type is not asked here. It adds nothing (no `add`, no `create_data`).
- `filter`, `facet` and `q`, like `page` and `per`, cannot be a step's `as`.

Every saved card is an `entry_updated`, so workflows that react to edits run once per changed card (Square's *list for sale* lists a piece whose price or shipping changed, or that was never listed). Saving a page at a time keeps that to at most a page of runs.

### When a step has nothing to show

A step that comes up empty says why, in plain words, and where to go from there. It is the same on every kind of step that lists something: a pick (`choose`, single or multi-select), a `list`, a `gallery`, a `run` and an `option` over templates.

| Key | What it does |
|---|---|
| `empty` | The step's own line for when there is nothing (*No lines in this beat yet.*), at most 300 characters. Without it the page says why itself: whose list it is (*The Tin Soldier has no cast member yet.*), which earlier choices narrow it (*No chapter belongs to what you chose in "Story" yet.*), that nothing fits what the step looks for, or that the workspace has none. Where the step can make one, it adds *Add the first one below.* |
| `empty_next` | Where the empty step points, as a button under the line: `{step}`, an earlier step of the same setup (*Go to "The story"*; `text` says it otherwise), or `{text, href}`, a path in the app, such as another setup (`/workspace/setups/open-call`). |

A pick with nothing to pick also offers **Change "…"** for each earlier choice that narrows it, and, when the choice is optional and nothing can be made on the step, **Go on without choosing**. A list, a gallery and a run keep their Continue button.

A `run` step whose `requires` is not met says what is missing by the field's own name (*"Voice" on The Young Man is empty, and this step needs it.*) and links to the earlier step that fills it: a `form` that shows the field, an `upload` into it, or a `run` whose `report` is that field. When no step of the setup fills it, the link opens the entry itself. It no longer also says that there is nothing to do.

### Moving around

Every step in the list at the top is a link, so you can jump ahead. A step that needs an earlier answer (a story list needs its world) opens on that earlier step instead, and says why. **Skip without saving →** at the bottom of a step goes on without it, the same on every kind of step; on an optional choice it also clears what was chosen there, and what later steps chose on the strength of it, as changing the choice would. A choice that is not optional has no skip: the steps after it need it.

`${name}` reads a choice made earlier. A setup ends with `next` (what to do after, with links) and `open` (a button that opens what was made, or its view). Field keys may be camelCase (`sellOnline`). A picture field is read under its role, so a type whose `image` field has `role: "featured"` shows the pictures attached as *featured*. The format is validated when the package is previewed; see `services/blueprints/wizards.py` for the exact rules.

## Workers

Some work is too heavy for the web server: cutting audio, rendering a video, converting a recording to mp3, working out a screenplay's chapters. That runs on a **worker**, a separate process that polls the workspace for **job** entries and writes the result back on the job.

- A worker registers the **kinds** of job it can do. A kind declares what it takes, what it gives and what it needs, so a bad job fails at once with the reason on its record.
- A package's workflows create jobs (a `job` entry with a `kind` and `args`); a worker picks them up. The worker image comes from the package's own repository, and which kinds a runner offers is set in its configuration.
- **Settings → Workers** shows which workers are alive, what each kind takes, the queue, and every job's log and result. A worker that is not running shows a grey dot, not a red one.
- Workers only reach out to Marvin; nothing listens. Install the package first (it brings the `job`, `job-kind` and `worker` record types), then run the worker with the workspace's credentials.

Workers matter to whoever runs the workspace's heavy workflows. People who only use a guided setup, such as adding artwork, never see one.
