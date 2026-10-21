"""Export a Playbook as a standard skill folder (https://agentskills.io): a zip with ``<name>/SKILL.md`` and the reference files
at their paths. ``SKILL.md`` is written by the same codec the import reads, so importing the zip gives back the Playbook; Marvin's
own settings sit under the frontmatter's ``metadata`` (``marvin-`` keys), which other tools ignore.
"""

import io
import zipfile

from marvin.services.playbooks import reference_files
from marvin.services.playbooks.skill_md import SkillDoc, render_skill_md


def export_playbook(session, entry, assets) -> tuple[str, bytes]:
    """``(file name, zip bytes)`` for a Playbook entry of any status. ``assets`` is an ``AssetStorageService`` of its workspace."""
    from marvin.db.models.platform.assets import Assets

    doc = SkillDoc.from_entry_data(entry.data_json or {}, (entry.metadata_json or {}).get("frontmatterExtra"))
    folder = doc.name
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{folder}/SKILL.md", render_skill_md(doc))
        for ref in reference_files(session, entry.id):
            z.writestr(f"{folder}/{ref.path}", assets.read_bytes(session.get(Assets, ref.asset_id)))
    return f"{folder}.zip", out.getvalue()
