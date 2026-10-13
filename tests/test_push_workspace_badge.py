# ruff: noqa: F811 — the `ws` / `workspace` fixtures are imported, then named as parameters
"""The installed app's icon count and workspace-aware notifications.

The icon shows the current workspace's inbox plus the person's conversations waiting for their approval in any
workspace; a workspace's push names that workspace, so tapping it switches there before the page opens.
"""

import json
import uuid
from types import SimpleNamespace

from marvin.services import push_actions, push_notifications, web_push
from tests import test_content_role_gates as gates
from tests.test_workflow_authoring import AD, P, workspace, ws  # noqa: F401 — fixtures


def _awaiting_thread(ws, *, group_id=None, child_of=None):
    from marvin.db.models.groups.ai_threads import THREAD_STATUS_AWAITING
    from marvin.services.ai.threads import create_thread

    thread = create_thread(ws.session, group_id or ws.gid, ws.uid, "marvin", "do it", None, None, parent_thread_id=child_of)
    thread.status = THREAD_STATUS_AWAITING
    ws.session.commit()
    return thread


def test_a_push_names_its_workspace():
    gid = str(uuid.uuid4())
    payload = json.loads(web_push.PushMessage(title="Hi", url="/x", workspace=gid).payload())
    assert payload["workspace"] == gid
    assert "workspace" not in json.loads(web_push.PushMessage(title="Hi").payload())  # a platform push has none


def test_every_workspace_push_is_sent_with_its_workspace(monkeypatch):
    sent = []
    monkeypatch.setattr(web_push, "send_to_users", lambda session, people, category, message: sent.append(message))
    gid = uuid.uuid4()

    push_notifications._send(None, gid, ["u"], web_push.ACTIVITY, web_push.PushMessage(title="New entry"))

    assert sent[0].workspace == str(gid)


def test_the_icon_counts_the_inbox_here_and_approvals_anywhere(ws):
    from marvin.db.models.groups import Groups

    admin = gates._sign_in(ws.workspace, AD)
    admin.post(f"{P}/entries", json={"entry_type_id": ws.et["id"], "title": "From a form", "status": "inbox"})
    other = Groups(session=ws.session, name=f"o-{uuid.uuid4().hex[:6]}", slug=f"o-{uuid.uuid4().hex[:6]}")
    ws.session.add(other)
    ws.session.commit()
    root = _awaiting_thread(ws)
    _awaiting_thread(ws, group_id=other.id)  # waits in another workspace: still counts
    _awaiting_thread(ws, child_of=root.id)  # a hand-off's specialist parks with its parent: counted once
    user = SimpleNamespace(id=ws.uid, active_group_id=ws.gid, group_id=ws.gid)

    assert push_actions.badge_counts(ws.session, user) == {"inbox": 1, "approvals": 2, "count": 3}
    assert admin.get("/api/self/push/badge").json() == {"inbox": 1, "approvals": 2, "count": 3}
