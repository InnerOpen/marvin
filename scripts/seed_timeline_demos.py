"""Sample entries for the Timeline Demos package (docs/examples/timeline-demos.marvin-package.json): one conference day and one two-week content plan.

A package carries no entries, so this makes them through the API, in the workspace the token acts in. It looks every entry up by its slug
first and makes only the missing ones, so it can be run again. It uses nothing but the standard library.

    MARVIN_API_URL=https://marvin.example.com MARVIN_TOKEN=... python scripts/seed_timeline_demos.py

MARVIN_API_URL is the API's base (the part before /api); MARVIN_TOKEN a token of someone who may make entries there (an Author or above).
Install the package first (Settings → Automation → Packages, or POST /api/groups/packages/install with the file): the entry types must exist.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

EVENT = "demo-northern-dev-day"
PLAN = "demo-spring-launch"
TIMEOUT_SECONDS = 30
QUERY_LIMIT = 500

# A conference day, in minutes from the doors opening. Each session: slug, title, part of the day, minutes, status, people, cues.
# People: (name, role, minutes or None for the whole session). Cues: (cue slug, minutes into the session).
SESSIONS = [
    ("doors", "Doors and coffee", "morning", 30, "ready", [], [("walk-in-music", 0)]),
    (
        "keynote",
        "Keynote: Shipping small",
        "morning",
        45,
        "ready",
        [("Priya Shah", "Host", 5), ("Tom Okafor", "Speaker", 35)],
        [("lights-down", 0), ("go-live", 0), ("slides-on", 5)],
    ),
    ("postgres", "Postgres for people in a hurry", "morning", 30, "ready", [("Mei Lin", "Speaker", 25)], [("slides-on", 0)]),
    ("break", "Break", "morning", 15, "ready", [], [("walk-in-music", 0)]),
    (
        "panel",
        "Panel: Hiring juniors in 2027",
        "morning",
        45,
        "review",
        [("Priya Shah", "Moderator", None), ("Sam Reyes", "Panelist", None), ("Ada Brooks", "Panelist", None), ("Ken Ito", "Panelist", None)],
        [("panel-mics", 0), ("go-live", 0)],
    ),
    ("lunch", "Lunch", "afternoon", 60, "ready", [], [("walk-in-music", 15)]),
    (
        "workshop",
        "Workshop: Accessible forms, hands on",
        "afternoon",
        60,
        "review",
        [("Jo Ellis", "Speaker", 50)],
        [("slides-on", 0), ("room-reset", 55)],
    ),
    (
        "lightning",
        "Lightning talks",
        "afternoon",
        30,
        "draft",
        [("Priya Shah", "Host", None), ("Ola Nowak", "Speaker", 8), ("Ravi Menon", "Speaker", 8), ("Lea Martin", "Speaker", 8)],
        [("go-live", 0)],
    ),
    ("closing", "Closing and drinks", "afternoon", 30, "draft", [("Priya Shah", "Host", 10)], [("go-off-air", 10), ("walk-out-music", 10)]),
]
BLOCKS = [("morning", "Morning", 1), ("afternoon", "Afternoon", 2)]
# The cue library the sessions place: slug, title, kind, minutes.
CUES = [
    ("walk-in-music", "Walk-in music", "Sound", 15),
    ("walk-out-music", "Walk-out music", "Sound", 20),
    ("lights-down", "Lights down", "Lights", 1),
    ("go-live", "Livestream: go live", "Video", 2),
    ("go-off-air", "Livestream: off air", "Video", 1),
    ("slides-on", "Slides on screen", "Video", 1),
    ("panel-mics", "Panel mics live", "Stage", 2),
    ("room-reset", "Room reset", "Stage", 5),
]

# A two-week content plan: one day each, Monday 1 March 2027 on; posts as (day, channel, title, status).
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PLAN_DAYS = 14
FIRST_DATE = 1  # 1 March
POSTS = [
    (1, "LinkedIn", "Something new is coming", "published"),
    (1, "Instagram", "Teaser: the first look", "published"),
    (2, "Newsletter", "Spring issue: what we have been building", "scheduled"),
    (4, "Instagram", "Behind the scenes", "scheduled"),
    (5, "LinkedIn", "Why we built it", "review"),
    (8, "Instagram", "Launch day", "review"),
    (8, "LinkedIn", "It is here", "review"),
    (8, "Newsletter", "Launch issue", "draft"),
    (10, "Instagram", "How people use it", "draft"),
    (12, "LinkedIn", "The first week in numbers", "draft"),
    (14, "Newsletter", "Thank you, and what is next", "draft"),
]
DAY_STATUS = {1: "ready", 2: "ready", 4: "ready", 5: "review", 8: "review"}


class Api:
    """The few calls the seed needs, with the token on each."""

    def __init__(self, base: str, token: str) -> None:
        self.base = base.rstrip("/")
        self.token = token

    def call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"{self.base}{path}", data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as e:
            sys.exit(f"{method} {path} failed: {e.code} {e.read().decode(errors='replace')[:300]}")

    def type_ids(self) -> dict[str, str]:
        return {t["slug"]: t["id"] for t in self.call("GET", "/api/platform/entry-types")}

    def existing(self, entry_type: str) -> set[str]:
        found = self.call("POST", "/api/platform/entries/query", {"spec": {"entry_type": entry_type}, "limit": QUERY_LIMIT})
        return {e["slug"] for e in found.get("entries", [])}


class Seeder:
    """Makes each entry unless one with its slug is already there, and says which it did."""

    def __init__(self, api: Api) -> None:
        self.api = api
        self.types = api.type_ids()
        missing = [
            t
            for t in ("demo-event", "demo-block", "demo-session", "demo-speaker", "demo-cue", "demo-plan", "demo-day", "demo-post")
            if t not in self.types
        ]
        if missing:
            sys.exit(f"Install the Timeline Demos package first: this workspace has no {', '.join(missing)}")
        self.have: dict[str, set[str]] = {}
        self.made = 0
        self.kept = 0

    def entry(self, entry_type: str, slug: str, title: str, data: dict) -> None:
        have = self.have.setdefault(entry_type, self.api.existing(entry_type))
        if slug in have:
            self.kept += 1
            return
        self.api.call(
            "POST",
            "/api/platform/entries",
            {"entryTypeId": self.types[entry_type], "slug": slug, "title": title, "status": "draft", "dataJson": data},
        )
        have.add(slug)
        self.made += 1
        print(f"  made {entry_type} {slug}: {title}")


def seed_event(s: Seeder) -> None:
    s.entry("demo-event", EVENT, "Northern Dev Day 2027", {"venue": "Harbour Hall, Leeds", "date": "2027-03-12", "status": "review"})
    for slug, title, order in BLOCKS:
        s.entry("demo-block", f"{EVENT}-{slug}", title, {"event": EVENT, "order": order})
    for slug, title, kind, minutes in CUES:
        s.entry("demo-cue", f"demo-cue-{slug}", title, {"kind": kind, "minutes": minutes})
    for order, (slug, title, block, minutes, status, people, cues) in enumerate(SESSIONS, 1):
        session = f"{EVENT}-{slug}"
        placed = [{"cue": f"demo-cue-{cue}", "at": at} for cue, at in cues]
        s.entry(
            "demo-session",
            session,
            title,
            {"event": EVENT, "block": f"{EVENT}-{block}", "order": order, "minutes": minutes, "status": status, "cues": placed},
        )
        for n, (name, role, speaks) in enumerate(people, 1):
            person = {"event": EVENT, "session": session, "role": role, "order": n, **({"minutes": speaks} if speaks else {})}
            s.entry("demo-speaker", f"{session}-{n}", name, person)


def seed_plan(s: Seeder) -> None:
    s.entry("demo-plan", PLAN, "Spring launch", {"starts": "Mon 1 Mar 2027", "goal": "Two weeks around the launch on the 8th.", "status": "review"})
    for day in range(1, PLAN_DAYS + 1):
        title = f"{WEEKDAYS[(day - 1) % len(WEEKDAYS)]} {FIRST_DATE + day - 1} Mar"
        s.entry("demo-day", f"{PLAN}-day-{day:02d}", title, {"plan": PLAN, "number": day, "status": DAY_STATUS.get(day, "draft")})
    for n, (day, channel, title, status) in enumerate(POSTS, 1):
        s.entry(
            "demo-post",
            f"{PLAN}-post-{n:02d}",
            title,
            {"plan": PLAN, "day": f"{PLAN}-day-{day:02d}", "channel": channel, "status": status, "order": n},
        )


def main() -> None:
    base, token = os.environ.get("MARVIN_API_URL"), os.environ.get("MARVIN_TOKEN")
    if not base or not token:
        sys.exit("Set MARVIN_API_URL (the API's base, before /api) and MARVIN_TOKEN (a token that may make entries).")
    seeder = Seeder(Api(base, token))
    print("Event agenda:")
    seed_event(seeder)
    print("Content plan:")
    seed_plan(seeder)
    print(f"Made {seeder.made} entries; {seeder.kept} were already there.")
    print(f"Open them at /workspace/views/event-agenda?entry={EVENT} and /workspace/views/content-plan?entry={PLAN}.")


if __name__ == "__main__":
    main()
