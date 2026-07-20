"""Notification Agent - Sends in-app notifications for workflow events.

Determines notification type from workflow state context and creates
Notification records in the database. Supports in-app notifications
stored in DB, extensible for future email/webhook channels.

Requirements: 4.3, 4.4, 12.1, 12.2, 12.3, 12.4, 12.5
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.database import Notification, SessionLocal
from app.core.logger import logger
from app.services.agents.base_agent import BaseAgent

# Supported notification types (from design doc)
NOTIFICATION_TYPES = (
    "completion",
    "failure",
    "approval_request",
    "deployment_success",
    "deployment_failure",
)

# Templates for notification content by type
NOTIFICATION_TEMPLATES = {
    "completion": {
        "title": "Workflow Completed",
        "message": "Workflow run {run_id} completed successfully.{deployment_info}",
    },
    "failure": {
        "title": "Workflow Stage Failed",
        "message": "Stage '{stage}' failed in workflow run {run_id}. Error: {error}",
    },
    "approval_request": {
        "title": "Approval Required",
        "message": "Stage '{stage}' in workflow run {run_id} requires your approval.",
    },
    "deployment_success": {
        "title": "Deployment Successful",
        "message": "Deployment for workflow run {run_id} is live at {deployment_url}.",
    },
    "deployment_failure": {
        "title": "Deployment Failed",
        "message": "Deployment failed for workflow run {run_id}. Reason: {error}",
    },
}


class NotificationAgent(BaseAgent):
    """Agent that creates in-app notifications for workflow events.

    Responsibilities (Req 12.1–12.5):
    - Determine notification type from workflow state context
    - Create Notification records in the database
    - Support completion, failure, approval_request, deployment_success,
      and deployment_failure notification types
    - Store notifications in-app (DB-backed), extensible for future channels
    """

    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Determine notification type from state and create DB record(s).

        Inspects the workflow state to decide which notification(s) to send:
        - completion: workflow finished successfully (Req 12.1, 4.3)
        - failure: a stage failed (Req 12.2, 4.4)
        - approval_request: copilot mode approval needed (Req 12.3)
        - deployment_success: deployment is live (Req 12.4)
        - deployment_failure: deployment failed (Req 12.4)
        """
        run_id = state.get("run_id", "")
        tenant_id = state.get("tenant_id", "")
        stage = state.get("stage", "")
        error = state.get("error", "")
        deployment_url = state.get("deployment_url", "")
        execution_mode = state.get("execution_mode", "copilot")
        initiated_by = state.get("initiated_by", "")

        notification_type = self._determine_notification_type(state)

        if not notification_type:
            logger.info(
                "NotificationAgent: no notification needed for run %s stage %s",
                run_id, stage,
            )
            return state

        # Determine recipients
        recipients = self._determine_recipients(state, notification_type)

        if not recipients:
            logger.warning(
                "NotificationAgent: no recipients for %s notification on run %s",
                notification_type, run_id,
            )
            return state

        # Build notification content
        title, message = self._build_content(notification_type, state)

        # Build context payload
        context = {
            "run_id": run_id,
            "stage": stage,
            "execution_mode": execution_mode,
            "notification_type": notification_type,
        }
        if error:
            context["error"] = error
        if deployment_url:
            context["deployment_url"] = deployment_url

        # Persist notification(s) in DB (Req 12.4)
        db = SessionLocal()
        try:
            for recipient_id in recipients:
                notification = Notification(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id or None,
                    user_id=recipient_id,
                    notification_type=notification_type,
                    title=title,
                    message=message,
                    context=context,
                    is_read=False,
                    sent_at=datetime.now(),
                    created_at=datetime.now(),
                )
                db.add(notification)

            db.commit()
            logger.info(
                "NotificationAgent: created %d '%s' notification(s) for run %s",
                len(recipients), notification_type, run_id,
            )
        except Exception as exc:
            db.rollback()
            logger.error(
                "NotificationAgent: failed to create notifications — %s", exc
            )
        finally:
            db.close()

        return state

    # ------------------------------------------------------------------
    # Notification type determination
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_notification_type(state: Dict[str, Any]) -> Optional[str]:
        """Determine the notification type based on workflow state context.

        Priority order:
        1. deployment_failure — deployment explicitly failed
        2. deployment_success — deployment is live
        3. failure — stage error present
        4. approval_request — copilot mode and approval required
        5. completion — workflow completed successfully
        """
        error = state.get("error", "")
        deployment_url = state.get("deployment_url", "")
        stage = state.get("stage", "")
        status = state.get("status", "")
        execution_mode = state.get("execution_mode", "copilot")
        approval_required = state.get("approval_required", False)

        # Check for deployment-specific outcomes
        if stage == "deploy" or status == "deploying":
            if error:
                return "deployment_failure"
            if deployment_url:
                return "deployment_success"

        # General failure
        if error:
            return "failure"

        # Approval request in copilot mode
        if execution_mode == "copilot" and approval_required:
            return "approval_request"

        # Workflow completion
        if status in ("completed", "done"):
            return "completion"

        # Also treat deploy stage with a URL and no error as completion
        if stage == "deploy" and deployment_url and not error:
            return "completion"

        return None

    # ------------------------------------------------------------------
    # Recipient determination
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_recipients(
        state: Dict[str, Any], notification_type: str
    ) -> List[str]:
        """Determine notification recipients based on type and state.

        - completion / failure / deployment_*: notify the user who initiated the run
        - approval_request: notify users with approver roles (from state)
        """
        recipients: List[str] = []
        initiated_by = state.get("initiated_by", "")

        if notification_type == "approval_request":
            # Approval notifications go to designated approvers
            approver_ids = state.get("approver_ids", [])
            if approver_ids:
                recipients.extend(approver_ids)
            elif initiated_by:
                # Fallback: notify the initiator if no approvers specified
                recipients.append(initiated_by)
        else:
            # All other notifications go to the run initiator (Req 12.1, 12.2)
            if initiated_by:
                recipients.append(initiated_by)

        # Deduplicate while preserving order
        seen = set()
        unique: List[str] = []
        for r in recipients:
            if r not in seen:
                seen.add(r)
                unique.append(r)
        return unique

    # ------------------------------------------------------------------
    # Content building
    # ------------------------------------------------------------------

    @staticmethod
    def _build_content(
        notification_type: str, state: Dict[str, Any]
    ) -> tuple:
        """Build notification title and message from templates.

        Returns:
            (title, message)
        """
        run_id = state.get("run_id", "unknown")
        stage = state.get("stage", "unknown")
        error = state.get("error", "No details available")
        deployment_url = state.get("deployment_url", "")

        template = NOTIFICATION_TEMPLATES.get(notification_type, {})
        title = template.get("title", "Workflow Notification")

        # Build deployment info suffix for completion notifications
        deployment_info = ""
        if deployment_url:
            deployment_info = f" Deployment URL: {deployment_url}"

        message_template = template.get("message", "Workflow event: {run_id}")

        try:
            message = message_template.format(
                run_id=run_id,
                stage=stage,
                error=error,
                deployment_url=deployment_url,
                deployment_info=deployment_info,
            )
        except KeyError:
            message = f"Workflow notification for run {run_id}"

        return title, message
