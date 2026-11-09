"""An upload may say what it was made from: `metadata.derived_from` naming an asset of the workspace (the picture editor's crop, a
batch's adjusted copy) makes the new asset a *version* of it, the way a workflow's derivative is recorded (`source_asset_id`, origin
"derived"), so the library folds it under its original and the asset's page lists it. A name that is not an asset here changes nothing."""

import json
import uuid

from marvin.db.models.users.roles import WorkspaceRole
from tests.test_content_role_gates import P, _sign_in, workspace  # noqa: F401  (the fixture)

E = WorkspaceRole.EDITOR


def _upload(client, name: str, metadata: dict | None = None):
    files = {"file": (f"{name}.txt", b"picture bytes stand in", "text/plain")}
    data = {"slug": f"{name}-{uuid.uuid4().hex[:6]}", "name": name}
    if metadata is not None:
        data["metadata"] = json.dumps(metadata)
    res = client.post(f"{P}/assets/upload", files=files, data=data)
    assert res.status_code == 201, res.text
    return res.json()


def test_an_upload_naming_its_source_becomes_a_version_of_it(workspace):  # noqa: F811
    client = _sign_in(workspace, E)
    original = _upload(client, "harbour")
    edited = _upload(client, "harbour-edited", {"derived_from": original["id"], "derivation": "edited:cropper"})

    assert edited["sourceAssetId"] == original["id"]
    assert edited["origin"] == "derived"
    assert edited["metadataJson"]["derived_from"] == original["id"]
    versions = client.get(f"{P}/assets", params={"source": original["id"]}).json()
    assert [a["id"] for a in versions] == [edited["id"]]


def test_a_source_that_is_not_an_asset_here_is_left_as_plain_metadata(workspace):  # noqa: F811
    client = _sign_in(workspace, E)
    stray = _upload(client, "stray", {"derived_from": str(uuid.uuid4())})
    garbage = _upload(client, "garbage", {"derived_from": "not-a-uuid"})

    assert stray["sourceAssetId"] is None and stray["origin"] == "upload"
    assert garbage["sourceAssetId"] is None and garbage["metadataJson"]["derived_from"] == "not-a-uuid"
