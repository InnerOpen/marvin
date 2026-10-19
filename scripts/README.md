# Marvin Scripts

Utility scripts for seeding, migration, and maintenance.

## Seed Scripts

### `seed_mashandburnco.py`

**Idempotent seed script for Mash & Burn Co. content.**

Imports complete website content from the [mashandburnco repository](https://github.com/iWobble/mashandburnco) into Marvin as structured Entry data.

**Usage:**
```bash
uv run scripts/seed_mashandburnco.py
```

**What it does:**
- ✅ Creates `mash-and-burn-co` workspace
- ✅ Sets up 5 entry types (Page, Project, etc.)
- ✅ Creates 10 collections (Projects, Jackets, etc.)
- ✅ Imports 7 workshop projects with full metadata
- ✅ Imports 5 static pages
- ✅ Creates ~40 resources (materials, hardware)
- ✅ Creates ~7 asset metadata placeholders
- ✅ **Automatically creates API client token for Publishing API**

**Idempotent:**
- Run multiple times without duplicates
- Updates existing records
- Safe for development and testing

**Output:**
```
============================================================
✅ Seed complete!
============================================================

📝 API Client Token (save this!):
   marvin_sk_...

🧪 Test the Publishing API:
   curl -H "Authorization: Bearer marvin_sk_..." \
     http://localhost:8080/api/publish/mash-and-burn-co/entries
```

**Documentation:** See [docs/MASH-AND-BURN-SEED.md](../docs/MASH-AND-BURN-SEED.md)

> The Instagram integration used to be seeded by `seed_instagram_auto_reply.py`. It now declares its
> own content (entry types, collections, scheduled tasks) through the SDK, and the workspace applies
> it from the blueprint catalog after review — see `services/blueprints/`.

---

## Future Scripts

Additional seed scripts can be added here for:
- Development test data
- Demo content
- Customer-specific imports
- Migration utilities

Each script should be:
- Idempotent (safe to rerun)
- Well-documented
- Self-contained
- Logged clearly
