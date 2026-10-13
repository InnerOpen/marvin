#!/usr/bin/env python3
"""
Mash & Burn Co. Seed Script

Idempotent script to import Mash & Burn Co. content into Marvin.
Can be run multiple times - will create missing records and update existing ones.

Usage:
    uv run scripts/seed_mashandburnco.py

Source: iWobble/mashandburnco (develop branch)
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from marvin.core.config import get_app_settings
from marvin.db.models.groups import Groups
from marvin.db.models.platform import (
    APIClients,
    Assets,
    Collections,
    Entries,
    EntryAssets,
    EntryCollections,
    EntryResources,
    EntryTypes,
    Resources,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

settings = get_app_settings()


# ============================================================================
# Data Models (from mashandburnco repo)
# ============================================================================

PROJECTS_DATA = [
    {
        "id": "project-008",
        "slug": "leather-tricorn-hat",
        "projectNumber": "Project 008",
        "title": "Leather Tricorn Hat",
        "category": "Historical Wear",
        "material": "Vegetable-Tanned Leather",
        "status": "prototype",
        "notes": "A period-inspired tricorn shaped for structure, weather, and workshop practicality.",
        "shortDescription": "A leather historical-wear experiment built around shape, stiffness, and age.",
        "story": [
            "The Leather Tricorn Hat started as a study in how much structure a simple piece of leather can hold.",
            "The goal is not costume gloss. It is a useful period form made with honest material, clean edges, and enough restraint to feel made rather than theatrical.",
            "This one is on the bench as a prototype while the brim shape, crown height, and finish are being tuned.",
        ],
        "designIntent": [
            "Translate a historical shape through durable workshop materials.",
            "Keep the form recognizable while letting the leather earn character with use.",
        ],
        "materialsList": [
            "Vegetable-Tanned Leather",
            "Hand-Shaped Brim",
            "Burnished Edge Work",
            "Waxed Thread",
            "Made in Raleigh, NC",
        ],
        "workshopVerdict": "Built Because I Could.",
        "started": "Shape Study",
        "buildStage": "Prototype",
        "leadTime": "Not Released",
        "madeIn": "Raleigh, NC",
        "care": "Brush clean. Condition sparingly. Keep its shape.",
        "details": [
            {"label": "Leather", "value": "Vegetable-Tanned"},
            {"label": "Build Stage", "value": "Prototype"},
            {"label": "Made In", "value": "Raleigh, NC"},
        ],
        "image": {
            "alt": "Leather tricorn hat on a workshop table",
            "tone": "leather",
        },
        "href": "/projects/leather-tricorn-hat",
    },
    {
        "id": "project-007",
        "slug": "18th-century-frock-coat",
        "projectNumber": "Project 007",
        "title": "18th Century Frock Coat",
        "category": "Historical Wear",
        "material": "Wool Broadcloth",
        "status": "in-progress",
        "notes": "A long-skirted historical coat built around proportion, movement, and hand-finished details.",
        "shortDescription": "A historical-wear build exploring period structure through durable cloth and careful tailoring.",
        "story": [
            "The 18th Century Frock Coat is a deeper study in shape than most workshop projects.",
            "Long skirts, structured fronts, cuffs, and period proportion all have to work together without turning the piece into a fragile display object.",
            "The build is still being worked through at the bench, with fit and movement leading the decisions.",
        ],
        "designIntent": [
            "Study historical tailoring through the lens of a working modern shop.",
            "Balance period silhouette with construction that can survive handling, movement, and wear.",
        ],
        "materialsList": [
            "Wool Broadcloth",
            "Linen Canvas Structure",
            "Hand-Finished Buttonholes",
            "Period-Inspired Cuffs",
            "Made in Raleigh, NC",
        ],
        "workshopVerdict": "Refused to Stay on Paper.",
        "started": "Pattern Draft",
        "buildStage": "Pattern & Fit",
        "leadTime": "In Progress",
        "madeIn": "Raleigh, NC",
        "care": "Brush after wear. Spot clean. Store shaped.",
        "details": [
            {"label": "Cloth", "value": "Wool Broadcloth"},
            {"label": "Build Stage", "value": "Pattern & Fit"},
            {"label": "Made In", "value": "Raleigh, NC"},
        ],
        "image": {
            "alt": "18th century frock coat pattern and wool on a cutting table",
            "tone": "historical",
        },
        "href": "/projects/18th-century-frock-coat",
    },
    {
        "id": "project-006",
        "slug": "foundry-jacket",
        "projectNumber": "Project 006",
        "title": "The Foundry Jacket",
        "category": "Jackets",
        "material": "12oz Japanese Selvedge Denim",
        "status": "current",
        "availability": "Available",
        "notes": "Built for the long haul. Reinforced where it matters.",
        "shortDescription": "Made one at a time in the workshop.",
        "story": [
            "The Foundry Jacket started as a simple idea: a work jacket that could handle real work and still look better with time.",
            "I built it from 12oz Japanese selvedge denim and reinforced it in all the right places. Every detail is considered. Every stitch is intentional.",
            "Built in small batches in the workshop. Built to last.",
        ],
        "designIntent": [
            "Keep the shape useful, restrained, and familiar.",
            "Let the denim, reinforcement, and wear pattern tell the story over time.",
        ],
        "materialsList": [
            "12oz Japanese Selvedge Denim",
            "Yarn-Dyed Herringbone Twill Lining",
            "Brass Button & Copper Rivets",
            "Triple Needle Felled Seams",
            "Reinforced Elbows",
            "Inside Pocket",
            "Made in Raleigh, NC",
        ],
        "workshopVerdict": "Probably Overbuilt.",
        "started": "Pattern Draft",
        "buildStage": "Current Build",
        "leadTime": "2-3 Weeks",
        "madeIn": "Raleigh, NC",
        "care": "Wash cold. Hang dry. Wear often.",
        "details": [
            {"label": "Lining", "value": "Yarn-Dyed Herringbone Twill"},
            {"label": "Hardware", "value": "Brass Button & Copper Rivets"},
            {"label": "Made In", "value": "Raleigh, NC"},
            {"label": "Lead Time", "value": "2-3 Weeks"},
        ],
        "featured": True,
        "image": {
            "alt": "The Foundry Jacket laid on a workshop table",
            "tone": "foundry",
        },
        "href": "/projects/foundry-jacket",
    },
    {
        "id": "project-005",
        "slug": "chore-coat",
        "projectNumber": "Project 005",
        "title": "Chore Coat",
        "category": "Jackets",
        "material": "Herringbone Twill",
        "status": "available",
        "availability": "Available",
        "notes": "A utility coat cut for movement and hard daily wear.",
        "shortDescription": "A simple outer layer for shop days, errands, and honest abuse.",
        "story": [
            "The Chore Coat is the sort of piece I reach for when I do not want to think too hard about what I am wearing.",
            "The shape is straightforward, the pockets are useful, and the fabric is chosen to take marks instead of pretending work is clean.",
            "It is quiet by design. The kind of jacket that earns its keep slowly.",
        ],
        "designIntent": [
            "Build a daily outer layer that works hard without shouting.",
            "Keep the pocketing generous and the silhouette easy to live in.",
        ],
        "materialsList": [
            "Herringbone Twill",
            "Reinforced Patch Pockets",
            "Bar-Tacked Stress Points",
            "Cotton Binding",
            "Made in Raleigh, NC",
        ],
        "workshopVerdict": "Built One at a Time.",
        "started": "Cutting Table",
        "buildStage": "Available",
        "leadTime": "Ready To Ship",
        "madeIn": "Raleigh, NC",
        "care": "Wash cold. Hang dry. Beat it up.",
        "details": [
            {"label": "Pockets", "value": "Oversized Patch Pockets"},
            {"label": "Construction", "value": "Reinforced Stress Points"},
            {"label": "Made In", "value": "Raleigh, NC"},
            {"label": "Lead Time", "value": "Ready To Ship"},
        ],
        "image": {
            "alt": "Chore coat on a wooden workshop bench",
            "tone": "olive",
        },
        "href": "/projects/chore-coat",
    },
    {
        "id": "project-004",
        "slug": "standard-issue-jean",
        "projectNumber": "Project 004",
        "title": "Standard Issue Jean",
        "category": "Other",
        "material": "14oz Selvedge Denim",
        "status": "in-progress",
        "notes": "Straightforward denim built to soften slowly.",
        "shortDescription": "A no-nonsense jean built around fabric, fit, and patience.",
        "story": [
            "The Standard Issue Jean is my answer to denim that tries too hard.",
            "The fabric does the work here: 14oz selvedge denim with enough structure to last and enough give to become personal over time.",
            "This project is still being tuned at the bench. Fit first, then details.",
        ],
        "designIntent": [
            "Make denim that feels ordinary in the best possible way.",
            "Prioritize fit, fabric behavior, and long-term wear over novelty.",
        ],
        "materialsList": [
            "14oz Selvedge Denim",
            "Copper Rivets",
            "Chain-Stitched Hem",
            "Leather Patch",
            "Made in Raleigh, NC",
        ],
        "workshopVerdict": "Worth the Extra Stitch.",
        "started": "Fit Block",
        "buildStage": "Fit Tuning",
        "leadTime": "In Progress",
        "madeIn": "Raleigh, NC",
        "care": "Wash cold when needed. Hang dry.",
        "details": [
            {"label": "Denim", "value": "14oz Selvedge"},
            {"label": "Hardware", "value": "Copper Rivets"},
            {"label": "Build Stage", "value": "Fit Tuning"},
            {"label": "Made In", "value": "Raleigh, NC"},
        ],
        "image": {
            "alt": "Folded selvedge denim jeans with label detail",
            "tone": "denim",
        },
        "href": "/projects/standard-issue-jean",
    },
    {
        "id": "project-003",
        "slug": "field-tote",
        "projectNumber": "Project 003",
        "title": "Field Tote",
        "category": "Totes & Bags",
        "material": "Waxed Canvas & Leather",
        "status": "prototype",
        "notes": "A carryall for patterns, tools, and daily workshop clutter.",
        "shortDescription": "A workshop tote built for useful messes.",
        "story": [
            "The Field Tote started as a place to put the things that never seem to have a place.",
            "Patterns, tools, notebooks, fabric scraps, coffee, errands. The bag needed to handle all of it without becoming precious.",
            "The prototype is about proportion: enough structure to stand up, enough softness to get out of the way.",
        ],
        "designIntent": [
            "Make a carryall that can handle the real mess of a working day.",
            "Balance structure, access, and materials that look better with use.",
        ],
        "materialsList": [
            "Waxed Canvas",
            "Vegetable-Tanned Leather Handles",
            "Bound Interior Seams",
            "Reinforced Bottom Panel",
            "Made in Raleigh, NC",
        ],
        "workshopVerdict": "Prototype Worth Keeping.",
        "started": "Bench Prototype",
        "buildStage": "Prototype",
        "leadTime": "Not Released",
        "madeIn": "Raleigh, NC",
        "care": "Brush clean. Spot clean. Re-wax as needed.",
        "details": [
            {"label": "Canvas", "value": "Waxed Cotton Canvas"},
            {"label": "Handles", "value": "Vegetable-Tanned Leather"},
            {"label": "Build Stage", "value": "Prototype"},
            {"label": "Made In", "value": "Raleigh, NC"},
        ],
        "image": {
            "alt": "Waxed canvas field tote with leather handles",
            "tone": "canvas",
        },
        "href": "/projects/field-tote",
    },
    {
        "id": "project-002",
        "slug": "watch-cap",
        "projectNumber": "Project 002",
        "title": "Watch Cap",
        "category": "Accessories",
        "material": "Merino Wool",
        "status": "small-run",
        "notes": "Warm, simple, and meant to disappear into daily use.",
        "shortDescription": "A small-run cap for cold mornings and long shop days.",
        "story": [
            "The Watch Cap is intentionally plain.",
            "Good wool, useful shape, no extra ceremony. It is made to be worn hard enough that you stop noticing it.",
            "Small runs keep the project manageable and let the details stay close.",
        ],
        "designIntent": [
            "Keep warmth and simplicity ahead of branding.",
            "Make a small object that disappears into daily use.",
        ],
        "materialsList": [
            "Merino Wool",
            "Rib Knit Construction",
            "Small Woven Mark",
            "Finished in Raleigh, NC",
        ],
        "workshopVerdict": "Would Build Again.",
        "started": "Small Run",
        "buildStage": "Small Run",
        "leadTime": "Limited Availability",
        "madeIn": "Raleigh, NC",
        "care": "Hand wash cold. Dry flat.",
        "details": [
            {"label": "Fiber", "value": "Merino Wool"},
            {"label": "Run", "value": "Small Batch"},
            {"label": "Build Stage", "value": "Small Run"},
            {"label": "Finished In", "value": "Raleigh, NC"},
        ],
        "image": {
            "alt": "Rib knit merino watch cap with small woven mark",
            "tone": "wool",
        },
        "href": "/projects/watch-cap",
    },
]

PAGES_DATA = [
    {
        "slug": "home",
        "title": "Home",
        "route": "/",
        "order": 1,
        "content": """# Mash & Burn Co.

Unnecessarily well-made.

Well-made projects, bench notes, and field-tested clothing.

## Brand Values

### Craft & Heritage
Traditional techniques. Honest materials. Timeless methods.

### Attention to Detail
The little things make the whole.

### Made by Hand
Built in small batches with purpose.

### Built to Last
Workwear that wears in, not out.
""",
    },
    {
        "slug": "projects",
        "title": "Projects",
        "route": "/projects",
        "order": 2,
        "content": """# Projects

Browse our collection of well-made pieces.

Each project is built one at a time in the workshop, with care given to materials, construction, and longevity.

From work jackets to accessories, every piece is designed to earn its keep over time.
""",
    },
    {
        "slug": "workshop",
        "title": "Workshop",
        "route": "/workshop",
        "order": 3,
        "content": """# The Workshop

A small shop in Raleigh, NC where every piece is built.

## Our Approach

We believe in making things the right way, not the fast way. Each project starts with honest materials and traditional techniques, refined through careful attention to detail.

The workshop is where ideas move from paper to pattern, from pattern to prototype, and from prototype to the pieces that leave here.

## What We Make

- **Jackets**: Work-ready outer layers built to last
- **Bags & Totes**: Carryalls for daily use
- **Accessories**: Small pieces with outsized utility
- **Historical Wear**: Period-inspired builds with modern durability

Every piece is made in small batches or one at a time, ensuring quality never gets lost in volume.
""",
    },
    {
        "slug": "about",
        "title": "About",
        "route": "/about",
        "order": 4,
        "content": """# About Mash & Burn Co.

Mash & Burn Co. is a small workshop in Raleigh, NC making well-considered pieces that get better with time.

## The Why

We started this because we were tired of things that didn't last. Tired of gear that looked good but fell apart. Tired of "heritage" marketing wrapped around cheaply made goods.

So we build the opposite: pieces made with honest materials, traditional techniques, and enough restraint to let the work speak for itself.

## The How

Every project starts at the bench. Pattern, prototype, refine. We keep runs small so quality stays high. We choose materials that earn character with use, not abuse.

The workshop verdict on each piece tells you what we really think. No marketing gloss.

## Contact

Have questions about a project? Want to inquire about custom work?

Email: hello@mashandburnco.com

An iWobble Labs Project
""",
    },
    {
        "slug": "contact",
        "title": "Contact",
        "route": "/contact",
        "order": 5,
        "content": """# Get in Touch

## Project Inquiries

Interested in a current project or have questions about availability?

Email us at: **hello@mashandburnco.com**

## Custom Work

We occasionally take on custom projects. Reach out with your idea and we'll let you know if it's a fit for the workshop.

## General Questions

For anything else, same email works: hello@mashandburnco.com

---

**Mash & Burn Co.**
Raleigh, NC
An iWobble Labs Project

Follow us:
- [Instagram](https://www.instagram.com/mashandburnco/)
- [Facebook](https://www.facebook.com/jaredmashburn)
- [Pinterest](https://www.pinterest.com/mashandburnco/)
- [YouTube](https://www.youtube.com/@mashandburnco)
""",
    },
]


# ============================================================================
# Helper Functions
# ============================================================================


def slugify_for_resource_type(text: str) -> str:
    """Convert text to a resource type slug."""
    return text.lower().replace(" ", "-").replace("&", "and")


def generate_markdown_from_project(project: dict) -> str:
    """Generate content_markdown from project data."""
    parts = []

    # Story
    if project.get("story"):
        parts.append("## Story\n")
        for paragraph in project["story"]:
            parts.append(f"{paragraph}\n")
        parts.append("\n")

    # Design Intent
    if project.get("designIntent"):
        parts.append("## Design Intent\n")
        for item in project["designIntent"]:
            parts.append(f"- {item}\n")
        parts.append("\n")

    # Materials
    if project.get("materialsList"):
        parts.append("## Materials & Construction\n")
        for item in project["materialsList"]:
            parts.append(f"- {item}\n")
        parts.append("\n")

    # Details
    if project.get("details"):
        parts.append("## Specifications\n")
        for detail in project["details"]:
            parts.append(f"**{detail['label']}**: {detail['value']}  \n")
        parts.append("\n")

    # Care
    if project.get("care"):
        parts.append(f"## Care\n{project['care']}\n\n")

    return "".join(parts)


def upsert_workspace(session, admin_user_id: str) -> Groups:
    """Create or update the Mash & Burn Co. workspace."""
    workspace_slug = "mash-and-burn-co"

    workspace = session.query(Groups).filter(Groups.slug == workspace_slug).first()

    if workspace:
        logger.info(f"✓ Workspace '{workspace_slug}' already exists")
        workspace.name = "Mash & Burn Co."
        session.commit()
    else:
        workspace = Groups(
            id=uuid4().hex,
            slug=workspace_slug,
            name="Mash & Burn Co.",
            session=session,
        )
        session.add(workspace)
        session.commit()
        logger.info(f"✓ Created workspace '{workspace_slug}'")

    return workspace


def upsert_site_configuration(session, workspace: Groups) -> None:
    """
    Configure site settings for the workspace.

    Replaces hardcoded site.ts with database-backed configuration.
    Values match the Mash & Burn Co. site.ts file.
    """
    from marvin.db.models.groups import GroupPreferencesModel

    # Get or create preferences for this workspace
    prefs = session.query(GroupPreferencesModel).filter(GroupPreferencesModel.group_id == workspace.id).first()

    if not prefs:
        prefs = GroupPreferencesModel(
            id=uuid4().hex,
            group_id=workspace.id,
            session=session,
        )
        session.add(prefs)
        session.flush()

    # Site identity (from site.ts)
    prefs.site_title = "Mash & Burn Co."
    prefs.site_tagline = "Unnecessarily well-made"
    prefs.site_description = "Well-made projects, bench notes, and field-tested clothing."
    prefs.site_contact_email = "hello@mashandburnco.com"

    # Social media links (from site.ts social object)
    prefs.site_social_json = {
        "instagram": "https://www.instagram.com/mashandburnco/",
        "facebook": "https://www.facebook.com/jaredmashburn",
        "pinterest": "https://www.pinterest.com/mashandburnco/",
        "youtube": "https://www.youtube.com/@mashandburnco",
    }

    # Additional metadata (from site.ts inquiry, brandAssets paths, etc.)
    prefs.site_metadata_json = {
        "imprint": "An iWobble Labs Project",
        "inquiry": {
            "label": "Project inquiries",
            "href": "/contact",
            "subject": "Project inquiry",
        },
        "brandAssets": {
            "monogram": "/assets/brand/monogram/mb-monogram.svg",
            "favicon": "/assets/brand/favicon/mb-favicon.svg",
        },
    }

    # Localization
    prefs.site_locale = "en-US"
    prefs.site_timezone = "America/New_York"

    session.commit()
    logger.info("  ✓ Configured site settings")


def upsert_entry_types(session, workspace: Groups) -> dict:
    """Create or update entry types. Returns dict of slug -> model."""
    entry_types_data = [
        {"slug": "page", "name": "Page", "description": "Static site pages"},
        {"slug": "project", "name": "Project", "description": "Workshop projects and products"},
        {"slug": "bench-note", "name": "Bench Note", "description": "Workshop notes and updates"},
        {"slug": "product", "name": "Product", "description": "Available products"},
        {"slug": "guide", "name": "Guide", "description": "How-to guides and resources"},
    ]

    entry_types = {}

    for data in entry_types_data:
        entry_type = session.query(EntryTypes).filter(EntryTypes.group_id == workspace.id, EntryTypes.slug == data["slug"]).first()

        if entry_type:
            logger.info(f"  ✓ Entry type '{data['slug']}' exists")
            entry_type.name = data["name"]
            entry_type.description = data.get("description")
            session.commit()
        else:
            entry_type = EntryTypes(
                id=uuid4().hex,
                group_id=workspace.id,
                slug=data["slug"],
                name=data["name"],
                description=data.get("description"),
                session=session,
            )
            session.add(entry_type)
            session.commit()
            logger.info(f"  ✓ Created entry type '{data['slug']}'")

        entry_types[data["slug"]] = entry_type

    return entry_types


def upsert_collections(session, workspace: Groups) -> dict:
    """Create or update collections. Returns dict of slug -> model."""
    collections_data = [
        {"slug": "site-pages", "name": "Site Pages", "description": "Main site pages", "sort_order": 1},
        {"slug": "projects", "name": "Projects", "description": "All workshop projects", "sort_order": 2},
        {"slug": "featured", "name": "Featured", "description": "Featured projects", "sort_order": 3},
        {"slug": "current-project", "name": "Current Project", "description": "Currently available project", "sort_order": 4},
        {"slug": "on-the-bench", "name": "On the Bench", "description": "Projects in progress", "sort_order": 5},
        {"slug": "jackets", "name": "Jackets", "description": "Work jackets and coats", "sort_order": 6, "icon": "work-jacket"},
        {"slug": "totes-and-bags", "name": "Totes & Bags", "description": "Bags and carryalls", "sort_order": 7, "icon": "field-tote"},
        {"slug": "accessories", "name": "Accessories", "description": "Small goods and accessories", "sort_order": 8, "icon": "watch-cap"},
        {"slug": "historical-wear", "name": "Historical Wear", "description": "Period-inspired pieces", "sort_order": 9, "icon": "historical-wear"},
        {"slug": "other", "name": "Other", "description": "Miscellaneous projects", "sort_order": 10},
    ]

    collections = {}

    for data in collections_data:
        collection = session.query(Collections).filter(Collections.group_id == workspace.id, Collections.slug == data["slug"]).first()

        if collection:
            logger.info(f"  ✓ Collection '{data['slug']}' exists")
            collection.name = data["name"]
            collection.description = data.get("description")
            collection.sort_order = data.get("sort_order")
            collection.icon = data.get("icon")
            session.commit()
        else:
            collection = Collections(
                id=uuid4().hex,
                group_id=workspace.id,
                slug=data["slug"],
                name=data["name"],
                description=data.get("description"),
                sort_order=data.get("sort_order"),
                icon=data.get("icon"),
                session=session,
            )
            session.add(collection)
            session.commit()
            logger.info(f"  ✓ Created collection '{data['slug']}'")

        collections[data["slug"]] = collection

    return collections


def upsert_project_entry(session, workspace: Groups, project_data: dict, entry_types: dict, collections: dict, admin_user_id: str) -> Entries:
    """Create or update a project entry with all relationships."""

    # Check if entry exists
    entry = session.query(Entries).filter(Entries.group_id == workspace.id, Entries.slug == project_data["slug"]).first()

    # Prepare entry data
    summary = project_data.get("shortDescription") or project_data.get("notes")
    description = project_data.get("notes")
    content_markdown = generate_markdown_from_project(project_data)

    # Metadata preservation
    metadata_json = {
        "id": project_data["id"],
        "projectNumber": project_data["projectNumber"],
        "category": project_data["category"],
        "material": project_data["material"],
        "projectStatus": project_data["status"],
        "availability": project_data.get("availability"),
        "workshopVerdict": project_data.get("workshopVerdict"),
        "started": project_data.get("started"),
        "completed": project_data.get("completed"),
        "hours": project_data.get("hours"),
        "series": project_data.get("series"),
        "buildStage": project_data.get("buildStage"),
        "leadTime": project_data.get("leadTime"),
        "madeIn": project_data.get("madeIn"),
        "care": project_data.get("care"),
        "details": project_data.get("details"),
        "imageTone": project_data.get("image", {}).get("tone"),
        "href": project_data["href"],
        "featured": project_data.get("featured", False),
    }

    if entry:
        logger.info(f"  ✓ Updating project entry '{project_data['slug']}'")
        entry.title = project_data["title"]
        entry.summary = summary
        entry.description = description
        entry.content_markdown = content_markdown
        entry.metadata_json = metadata_json
        session.commit()
    else:
        entry = Entries(
            id=uuid4().hex,
            group_id=workspace.id,
            entry_type_id=entry_types["project"].id,
            slug=project_data["slug"],
            title=project_data["title"],
            summary=summary,
            description=description,
            content_markdown=content_markdown,
            status="published",
            published_at=datetime.now(UTC),
            metadata_json=metadata_json,
            created_by=admin_user_id,
            session=session,
        )
        session.add(entry)
        session.commit()
        logger.info(f"  ✓ Created project entry '{project_data['slug']}'")

    # Attach to collections
    collection_slugs = ["projects"]  # Every project goes to Projects

    # Featured project
    if project_data.get("featured"):
        collection_slugs.extend(["featured", "current-project"])
    else:
        collection_slugs.append("on-the-bench")

    # Category collection
    category_slug = project_data["category"].lower().replace(" ", "-").replace("&", "and")
    collection_slugs.append(category_slug)

    # Remove existing collection associations
    session.query(EntryCollections).filter(EntryCollections.entry_id == entry.id).delete()

    # Add new associations
    for coll_slug in collection_slugs:
        if coll_slug in collections:
            ec = EntryCollections(
                id=uuid4().hex,
                entry_id=entry.id,
                collection_id=collections[coll_slug].id,
            )
            session.add(ec)

    session.commit()

    # Create resources from materials
    upsert_project_resources(session, workspace, entry, project_data, admin_user_id)

    # Create asset placeholders
    upsert_project_assets(session, workspace, entry, project_data, admin_user_id)

    return entry


def upsert_project_resources(session, workspace: Groups, entry: Entries, project_data: dict, admin_user_id: str):
    """Create resources for a project entry."""

    # Remove existing resource associations
    session.query(EntryResources).filter(EntryResources.entry_id == entry.id).delete()

    resources_to_create = []

    # Primary material
    if project_data.get("material"):
        resources_to_create.append(
            {
                "name": project_data["material"],
                "resource_type": "material",
                "role": "primary-material",
                "position": 1,
            }
        )

    # Materials list
    if project_data.get("materialsList"):
        for idx, material in enumerate(project_data["materialsList"], start=2):
            # Determine resource type
            material_lower = material.lower()
            if "rivet" in material_lower or "button" in material_lower or "hardware" in material_lower:
                resource_type = "hardware"
            elif "made in" in material_lower or "finished in" in material_lower:
                resource_type = "location"
            elif any(word in material_lower for word in ["stitch", "seam", "construction", "tacked"]):
                resource_type = "construction"
            else:
                resource_type = "material"

            resources_to_create.append(
                {
                    "name": material,
                    "resource_type": resource_type,
                    "role": "component",
                    "position": idx,
                }
            )

    # Track which resources we've already linked to avoid duplicates
    linked_resource_ids = set()

    # Create/link resources
    for res_data in resources_to_create:
        # Find or create resource
        resource_slug = slugify_for_resource_type(res_data["name"])

        resource = session.query(Resources).filter(Resources.group_id == workspace.id, Resources.slug == resource_slug).first()

        if not resource:
            resource = Resources(
                session=session,
                id=uuid4().hex,
                group_id=workspace.id,
                slug=resource_slug,
                name=res_data["name"],
                resource_type=res_data["resource_type"],
                created_by=admin_user_id,
            )
            session.add(resource)
            session.commit()

        # Skip if we've already linked this resource to this entry
        if resource.id in linked_resource_ids:
            continue

        linked_resource_ids.add(resource.id)

        # Link to entry
        entry_resource = EntryResources(
            id=uuid4().hex,
            entry_id=entry.id,
            resource_id=resource.id,
            role=res_data.get("role"),
            position=res_data.get("position"),
        )
        session.add(entry_resource)

    session.commit()


def upsert_project_assets(session, workspace: Groups, entry: Entries, project_data: dict, admin_user_id: str):
    """Create asset metadata placeholders for a project entry."""

    # Remove existing asset associations
    session.query(EntryAssets).filter(EntryAssets.entry_id == entry.id).delete()

    assets_to_create = []

    # Featured image
    if project_data.get("featuredImage"):
        assets_to_create.append(
            {
                "name": f"{project_data['title']} - Hero Image",
                "role": "hero",
                "alt_text": project_data["featuredImage"].get("alt", project_data["image"]["alt"]),
                "position": 1,
            }
        )
    else:
        # Placeholder from image.alt
        assets_to_create.append(
            {
                "name": f"{project_data['title']} - Hero Image",
                "role": "hero",
                "alt_text": project_data["image"]["alt"],
                "position": 1,
            }
        )

    # Support images
    if project_data.get("supportImages"):
        for idx, support_img in enumerate(project_data["supportImages"], start=2):
            assets_to_create.append(
                {
                    "name": f"{project_data['title']} - {support_img['usage'].title()}",
                    "role": support_img["usage"],
                    "alt_text": support_img.get("alt", ""),
                    "position": idx,
                }
            )

    # Create assets
    for asset_data in assets_to_create:
        asset_slug = slugify_for_resource_type(asset_data["name"])

        asset = session.query(Assets).filter(Assets.group_id == workspace.id, Assets.slug == asset_slug).first()

        if not asset:
            filename = f"{asset_slug}.jpg"
            asset = Assets(
                session=session,
                id=uuid4().hex,
                group_id=workspace.id,
                slug=asset_slug,
                name=asset_data["name"],
                original_filename=filename,
                filename=filename,
                extension="jpg",
                file_path=f"/placeholder/{filename}",  # Placeholder path
                file_size=0,  # Placeholder size
                mime_type="image/jpeg",  # Placeholder
                asset_type="image",
                checksum="placeholder",
                storage_provider="local",
                storage_key=f"placeholder/{filename}",
                alt_text=asset_data["alt_text"],
                uploaded_by=admin_user_id,
            )
            session.add(asset)
            session.commit()

        # Link to entry
        entry_asset = EntryAssets(
            id=uuid4().hex,
            entry_id=entry.id,
            asset_id=asset.id,
            role=asset_data["role"],
            position=asset_data["position"],
        )
        session.add(entry_asset)

    session.commit()


def create_api_client_for_workspace(session, workspace: Groups, admin_user_id: str):
    """Create an API client for the workspace's Publishing API."""
    import secrets

    from marvin.core.security.hasher import get_hasher

    # Check if API client already exists
    existing_client = session.query(APIClients).filter(APIClients.group_id == workspace.id, APIClients.slug == "publishing-api-client").first()

    if existing_client:
        logger.info(f"  ✓ API client already exists: {existing_client.name}")

        # We can't return the plaintext token for existing clients
        # User will need to rotate the token if they lost it
        class ExistingClient:
            def __init__(self, name, note):
                self.name = name
                self.token = "<existing - rotate token to get new one>"

        return ExistingClient(existing_client.name, "Token not available for existing clients")

    # Generate new token
    token_prefix = settings.SECURITY_TOKEN_PREFIX_CLIENT
    random_part = secrets.token_urlsafe(settings.SECURITY_TOKEN_RANDOM_BYTES)
    plaintext_token = f"{token_prefix}{random_part}"
    token_hash = get_hasher().hash(plaintext_token)

    # Create API client
    api_client = APIClients(
        id=uuid4().hex,
        group_id=workspace.id,
        name="Mash & Burn Publishing API",
        slug="publishing-api-client",
        token_hash=token_hash,
        permissions={"read:published_entries": True},
        enabled=True,
        created_by=admin_user_id,
        session=session,
    )
    session.add(api_client)
    session.commit()

    # Return object with plaintext token
    class APIClientWithToken:
        def __init__(self, name, token):
            self.name = name
            self.token = token

    return APIClientWithToken(api_client.name, plaintext_token)


def upsert_page_entry(session, workspace: Groups, page_data: dict, entry_types: dict, collections: dict, admin_user_id: str) -> Entries:
    """Create or update a page entry."""

    entry = session.query(Entries).filter(Entries.group_id == workspace.id, Entries.slug == page_data["slug"]).first()

    metadata_json = {
        "route": page_data["route"],
        "order": page_data["order"],
    }

    if entry:
        logger.info(f"  ✓ Updating page entry '{page_data['slug']}'")
        entry.title = page_data["title"]
        entry.content_markdown = page_data["content"]
        entry.metadata_json = metadata_json
        session.commit()
    else:
        entry = Entries(
            id=uuid4().hex,
            group_id=workspace.id,
            entry_type_id=entry_types["page"].id,
            slug=page_data["slug"],
            title=page_data["title"],
            content_markdown=page_data["content"],
            status="published",
            published_at=datetime.now(UTC),
            metadata_json=metadata_json,
            created_by=admin_user_id,
            session=session,
        )
        session.add(entry)
        session.commit()
        logger.info(f"  ✓ Created page entry '{page_data['slug']}'")

    # Attach to Site Pages collection
    session.query(EntryCollections).filter(EntryCollections.entry_id == entry.id).delete()

    ec = EntryCollections(
        id=uuid4().hex,
        entry_id=entry.id,
        collection_id=collections["site-pages"].id,
    )
    session.add(ec)
    session.commit()

    return entry


# ============================================================================
# Main Seed Function
# ============================================================================


def seed_mashandburnco():
    """Main seed function."""
    logger.info("=" * 60)
    logger.info("Mash & Burn Co. Seed Script")
    logger.info("=" * 60)

    # Create database connection
    engine = create_engine(settings.DB_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Get admin user (assume first admin)
        from marvin.db.models.users import Users

        admin_user = session.query(Users).filter(Users.admin.is_(True)).first()

        if not admin_user:
            logger.error("❌ No admin user found. Create an admin user first.")
            return

        admin_user_id = admin_user.id
        logger.info(f"Using admin user: {admin_user.username}")
        logger.info("")

        # 1. Upsert workspace
        logger.info("1. Setting up workspace...")
        workspace = upsert_workspace(session, admin_user_id)
        upsert_site_configuration(session, workspace)

        # Add admin as workspace OWNER
        from marvin.db.models.users.roles import WorkspaceRole
        from marvin.db.models.users.workspace_members import WorkspaceMembers

        existing_membership = (
            session.query(WorkspaceMembers).filter(WorkspaceMembers.user_id == admin_user_id, WorkspaceMembers.group_id == workspace.id).first()
        )

        if not existing_membership:
            admin_membership = WorkspaceMembers(session=session, user_id=admin_user_id, group_id=workspace.id, workspace_role=WorkspaceRole.OWNER)
            session.add(admin_membership)
            session.commit()
            logger.info("  ✓ Added admin as workspace OWNER")
        else:
            logger.info("  ✓ Admin already a workspace member")

        logger.info("")

        # 2. Upsert entry types
        logger.info("2. Setting up entry types...")
        entry_types = upsert_entry_types(session, workspace)
        logger.info("")

        # 3. Upsert collections
        logger.info("3. Setting up collections...")
        collections = upsert_collections(session, workspace)
        logger.info("")

        # 4. Upsert project entries
        logger.info(f"4. Importing {len(PROJECTS_DATA)} projects...")
        for project_data in PROJECTS_DATA:
            upsert_project_entry(session, workspace, project_data, entry_types, collections, admin_user_id)
        logger.info("")

        # 5. Upsert page entries
        logger.info(f"5. Importing {len(PAGES_DATA)} pages...")
        for page_data in PAGES_DATA:
            upsert_page_entry(session, workspace, page_data, entry_types, collections, admin_user_id)
        logger.info("")

        # 6. Create API client for this workspace
        logger.info("6. Creating API client for Publishing API...")
        api_client = create_api_client_for_workspace(session, workspace, admin_user_id)
        logger.info(f"  ✓ Created API client: {api_client.name}")
        logger.info("")

        logger.info("=" * 60)
        logger.info("✅ Seed complete!")
        logger.info("=" * 60)
        logger.info("")
        logger.info("📝 API Client Token (save this!):")
        logger.info(f"   {api_client.token}")
        logger.info("")
        logger.info("🧪 Test the Publishing API:")
        logger.info(f'   curl -H "Authorization: Bearer {api_client.token}" \\')
        logger.info(f"     http://localhost:8080/api/publish/{workspace.slug}/entries")
        logger.info("")
        logger.info("📚 Example Queries:")
        logger.info(f"   - Workspace info: GET /api/publish/{workspace.slug}")
        logger.info(f"   - Site configuration: GET /api/publish/{workspace.slug}/site")
        logger.info(f"   - All entries: GET /api/publish/{workspace.slug}/entries")
        logger.info(f"   - Specific project: GET /api/publish/{workspace.slug}/entries/foundry-jacket")
        logger.info(f"   - Collections: GET /api/publish/{workspace.slug}/collections")

    except Exception as e:
        logger.error(f"❌ Seed failed: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    seed_mashandburnco()
