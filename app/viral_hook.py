"""
app/viral_hook.py
─────────────────
Segment 6 — Viral onboarding: fires when a task is assigned to someone
who has no DB user account. Sends them a Slack DM with a one-click invite link.

Call send_viral_invite_if_needed() right after a task is created.
It is fire-and-forget — never raises, never blocks the main response.
"""

import logging
import os
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")


def send_viral_invite_if_needed(
    db: Session,
    task_id: int,
    assignee_name: Optional[str],
    assignee_slack_id: Optional[str],
    workspace_id: Optional[int],
    bolt_client,                      # slack_bolt client — passed from main.py handler
) -> None:
    """
    Called after every task creation. If the assignee has no DB account,
    send them a Slack DM with a viral invite link.

    Deduplicates — only one invite DM per assignee per workspace.
    Silent on all errors (non-blocking).
    """
    if not assignee_name or not assignee_slack_id or not workspace_id:
        return

    try:
        from app import crud
        from app.models import PendingInvite

        # 1. Is this person already a registered user?
        existing_user = crud.get_user_by_slack_id(db, assignee_slack_id)
        if existing_user:
            logger.debug(
                "viral_hook: %s is already registered — skipping invite",
                assignee_name,
            )
            return

        # 2. Already sent an invite to this person in this workspace?
        existing_invite = crud.get_pending_invite(db, workspace_id, assignee_name)
        if existing_invite:
            logger.debug(
                "viral_hook: invite already exists for %s in workspace %d — skipping",
                assignee_name, workspace_id,
            )
            return

        # 3. Create the invite record
        invite = crud.create_pending_invite(
            db,
            workspace_id      = workspace_id,
            assignee_name     = assignee_name,
            assignee_slack_id = assignee_slack_id,
            task_id           = task_id,
        )

        # 4. Build the claim URL
        claim_url = f"{FRONTEND_URL}/join?invite={invite.invite_token}"
        if not FRONTEND_URL:
            claim_url = f"/join?invite={invite.invite_token}"

        # 5. Send the DM
        workspace = crud.get_workspace_by_id(db, workspace_id)
        workspace_name = workspace.name if workspace else "your team"

        message = (
            f"👋 Hey *{assignee_name}*, you've been assigned a task in *{workspace_name}*.\n\n"
            f"Click below to claim it, see your full task list, and get notified about deadlines.\n\n"
            f"<{claim_url}|✅ Claim your task & join {workspace_name}>"
        )

        bolt_client.chat_postMessage(
            channel=assignee_slack_id,
            text=message,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"👋 Hey *{assignee_name}*! You've been assigned a task "
                            f"in *{workspace_name}*."
                        ),
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "Click below to claim it and see your full task list. "
                            "Takes 30 seconds to set up."
                        ),
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "✅ Claim my task"},
                            "style": "primary",
                            "url": claim_url,
                        }
                    ],
                },
            ],
        )

        logger.info(
            "viral_hook: sent invite DM to %s (%s) for task %d in workspace %d",
            assignee_name, assignee_slack_id, task_id, workspace_id,
        )

    except Exception as exc:
        # Never crash the main request
        logger.warning("viral_hook: non-fatal error — %s", exc)
