"""Web Push for the signed-in user (Profile → Notifications): the server's push key, this user's devices and
which kinds of push they take. Everything is the caller's own — another user's devices are never listed,
changed or reached. Without VAPID settings push is off: GET says so and nothing can be subscribed or sent.
See services/web_push.py.

One route takes no session: a notification's Approve / Deny (``public_router``), authorised by the single-use
token that notification carries (services/push_actions.py).
"""

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import UUID4
from sqlalchemy.orm import Session

from marvin.core.root_logger import get_logger
from marvin.db.db_setup import generate_session
from marvin.db.models.users import Users
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.routers import UserAPIRouter
from marvin.schemas.user.push import (
    PushApprovalAction,
    PushApprovalResult,
    PushCategoryRead,
    PushDeviceRead,
    PushPreferencesUpdate,
    PushSettingsRead,
    PushSubscriptionCreate,
    PushTestResult,
)
from marvin.services import push_actions, web_push
from marvin.services.event_bus_service.event_bus_service import EventBusService

logger = get_logger(__name__)

router = UserAPIRouter(prefix="/self/push", tags=["User: Self Service"])
public_router = APIRouter(prefix="/self/push", tags=["User: Self Service"])

TEST_MESSAGE = web_push.PushMessage(
    title="Test notification from Marvin",
    body="Push works on this device. Nothing is wrong.",
    url="/user/profile#notifications",
    tag="push-test",
)


def _send_test(user_id) -> None:
    """In the background: a fresh session, since the request's is closed by then."""
    from marvin.db.db_setup import session_context

    with session_context() as session:
        web_push.send_to_subscriptions(session, web_push.devices(session, user_id), TEST_MESSAGE)


@controller(router)
class UserPushController(BaseUserController):
    def _me(self) -> Users:
        user = self.session.get(Users, self.user.id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in.")
        return user

    def _require_push(self) -> None:
        if not web_push.configured():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Web Push isn't set up on this server.")

    def _read(self) -> PushSettingsRead:
        me = self._me()
        chosen = web_push.preferences(me)
        return PushSettingsRead(
            enabled=web_push.configured(),
            public_key=web_push.public_key(),
            categories=[
                PushCategoryRead(key=c.key, label=c.label, description=c.description, enabled=chosen[c.key]) for c in web_push.categories_for(me)
            ],
            devices=[PushDeviceRead.model_validate(d, from_attributes=True) for d in web_push.devices(self.session, me.id)],
        )

    @router.get("", response_model=PushSettingsRead, summary="Get My Push Settings")
    def get_push(self) -> PushSettingsRead:
        return self._read()

    @router.put("/preferences", response_model=PushSettingsRead, summary="Choose Which Pushes I Get")
    def update_preferences(self, data: PushPreferencesUpdate) -> PushSettingsRead:
        web_push.set_preferences(self.session, self._me(), data.categories)
        return self._read()

    @router.post("/subscriptions", status_code=status.HTTP_201_CREATED, response_model=PushDeviceRead, summary="Turn On Push for This Device")
    def subscribe(self, data: PushSubscriptionCreate, request: Request) -> PushDeviceRead:
        self._require_push()
        try:
            row = web_push.subscribe(
                self.session,
                self._me(),
                endpoint=data.endpoint.strip(),
                p256dh=data.keys.p256dh,
                auth=data.keys.auth,
                user_agent=data.user_agent or request.headers.get("user-agent"),
                label=data.label,
                replaces=data.replaces,
            )
        except web_push.InvalidSubscription as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        return PushDeviceRead.model_validate(row, from_attributes=True)

    @router.delete("/subscriptions", status_code=status.HTTP_204_NO_CONTENT, summary="Turn Off Push for This Device")
    def unsubscribe_endpoint(self, endpoint: str) -> None:
        web_push.unsubscribe(self.session, self.user.id, endpoint=endpoint)  # gone already is fine

    @router.delete("/subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove One of My Devices")
    def unsubscribe(self, subscription_id: UUID4) -> None:
        if not web_push.unsubscribe(self.session, self.user.id, subscription_id=subscription_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such device.")

    @router.post("/test", status_code=status.HTTP_202_ACCEPTED, response_model=PushTestResult, summary="Send a Test Push to My Devices")
    def send_test(self, bg_tasks: BackgroundTasks) -> PushTestResult:
        self._require_push()
        count = len(web_push.devices(self.session, self.user.id))
        if count:
            bg_tasks.add_task(_send_test, self.user.id)
        return PushTestResult(devices=count)


def _as_owner(session: Session, claim: push_actions.Claim):
    """The approval's owner, in the approval's workspace — who the Ask page's resume runs as."""
    from marvin.repos.all_repositories import get_repositories

    user = get_repositories(session, group_id=None).users.get_one(claim.user_id, "id", any_case=False)
    group_id = claim.thread.group_id
    if user is None or not (user.admin or any(str(m.group_id) == str(group_id) for m in user.workspace_memberships)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You're no longer a member of that workspace.")
    return user, user.model_copy(update={"active_group_id": group_id})


@public_router.post("/approvals/{approval_id}/{decision}", response_model=PushApprovalResult, summary="Approve or Deny from a Notification")
def decide_from_notification(
    approval_id: UUID4,
    decision: Literal["approve", "deny"],
    data: PushApprovalAction,
    session: Session = Depends(generate_session),
    event_bus: EventBusService = Depends(EventBusService.as_dependency),
) -> PushApprovalResult:
    """The Approve / Deny buttons of an AI-approval notification: the token it carries, no session. Runs the
    Ask page's resume as the approval's owner; results land in the conversation."""
    from marvin.routes.ai.operations_controller import AIOperationsController
    from marvin.schemas.group.ai_thread import AIThreadResumeRequest
    from marvin.services.push_notifications import ASK_PATH

    try:
        claim = push_actions.claim(session, approval_id, data.token, decision)
    except push_actions.Refused as e:
        logger.info(f"Push action refused for approval {approval_id}: {e.message}")
        raise HTTPException(status_code=e.status, detail=e.message) from e
    user, as_owner = _as_owner(session, claim)
    thread_id = str(claim.thread.id)
    logger.info(f"Push action: {decision} approval {thread_id} by user {user.id}")
    controller_ = AIOperationsController(session=session, user=as_owner, event_bus=event_bus)
    resume = AIThreadResumeRequest(decisions={str(c["id"]): decision for c in claim.calls}, source="ask_page")
    response = controller_.decide_parked(thread_id, resume, surface=push_actions.SURFACE)
    current = str(user.active_group_id or user.group_id) == str(claim.thread.group_id)
    return PushApprovalResult(
        decision=decision,
        message=push_actions.confirmation(decision, claim.calls, response),
        url=f"{ASK_PATH}?thread={quote(thread_id)}",
        badge=push_actions.inbox_count(session, claim.thread.group_id) if current else None,
    )
