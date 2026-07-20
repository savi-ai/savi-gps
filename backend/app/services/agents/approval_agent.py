"""Approval Agent - Manages approval checkpoints in Copilot mode.

Creates approval request records, records decisions, enforces role-based
permissions, and passes rejection feedback to state for stage re-execution.

Requirements: 5.3, 5.4, 9.1, 9.2, 9.3, 9.4, 9.5
"""
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session

from app.core.database import SessionLocal, Approval, AuditTrail, UserRole, Role
from app.core.logger import logger
from app.services.agents.base_agent import BaseAgent


class ApprovalAgent(BaseAgent):
    """Agent that manages approval checkpoints in Copilot mode.

    Responsibilities:
    - Create approval request records (Req 9.1)
    - Record approval/rejection decisions with audit trail (Req 9.2, 9.5)
    - Enforce role-based approval permissions (Req 9.4)
    - Pass rejection feedback to state for stage re-execution (Req 9.3)
    """

    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Process an approval checkpoint.

        In Copilot mode, creates an approval request if one doesn't already
        exist for the current stage. If a decision has been recorded on the
        existing approval, updates state accordingly.
        """
        execution_mode = state.get("execution_mode", "copilot")
        if execution_mode != "copilot":
            logger.info("ApprovalAgent: skipping — execution_mode is '%s'", execution_mode)
            return state

        stage = state.get("stage", "")
        project_id = state.get("project_id", "")
        workflow_run_id = state.get("run_id", "")
        user_id = state.get("initiated_by", "")
        tenant_id = state.get("tenant_id", "")

        if not stage or not project_id:
            logger.warning("ApprovalAgent: missing stage or project_id, skipping")
            return state

        db = SessionLocal()
        try:
            # Check for an existing pending approval for this run + stage
            existing = (
                db.query(Approval)
                .filter(
                    Approval.workflow_run_id == workflow_run_id,
                    Approval.step_name == stage,
                    Approval.status == "pending",
                )
                .first()
            )

            if existing:
                # Approval already exists — check if a decision was recorded
                if existing.decision:
                    return self._apply_decision(state, existing)
                # Still pending — mark state as awaiting approval
                state["approval_required"] = True
                logger.info(
                    "ApprovalAgent: approval %s still pending for stage '%s'",
                    existing.id,
                    stage,
                )
                return state

            # Determine target roles for this stage
            target_roles = self._get_target_roles_for_stage(stage)

            # Create a new approval request (Req 9.1)
            approval = self.create_approval_request(
                db=db,
                project_id=project_id,
                stage=stage,
                user_id=user_id,
                target_roles=target_roles,
                tenant_id=tenant_id,
                workflow_run_id=workflow_run_id,
            )

            state["approval_required"] = True
            # Track approval in state history
            approvals = state.get("approvals", [])
            approvals.append({
                "approval_id": approval.id,
                "stage": stage,
                "status": "pending",
                "created_at": approval.created_at.isoformat() if approval.created_at else None,
            })
            state["approvals"] = approvals

            logger.info(
                "ApprovalAgent: created approval %s for stage '%s' (roles: %s)",
                approval.id,
                stage,
                target_roles,
            )
        except Exception as e:
            logger.error("ApprovalAgent: error processing approval — %s", e)
            state["error"] = f"Approval processing failed: {e}"
        finally:
            db.close()

        return state

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def create_approval_request(
        self,
        db: Session,
        project_id: str,
        stage: str,
        user_id: str,
        target_roles: List[str],
        tenant_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
    ) -> Approval:
        """Create an Approval record with status='pending' (Req 9.1).

        Args:
            db: Database session.
            project_id: The project this approval belongs to.
            stage: The workflow stage name.
            user_id: The user who initiated the workflow / requested approval.
            target_roles: Roles that are allowed to approve this stage.
            tenant_id: Tenant scope.
            workflow_run_id: The workflow run this approval belongs to.

        Returns:
            The newly created Approval record.
        """
        approval = Approval(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            step_name=stage,
            from_user_id=user_id,
            to_roles=target_roles,
            status="pending",
            created_at=datetime.now(),
        )
        db.add(approval)
        db.commit()
        db.refresh(approval)
        return approval

    def record_decision(
        self,
        db: Session,
        approval_id: str,
        decision: str,
        approver_id: str,
        comments: Optional[str] = None,
    ) -> Approval:
        """Record an approval decision and log to AuditTrail (Req 9.2, 9.4, 9.5).

        Args:
            db: Database session.
            approval_id: The approval record to update.
            decision: 'approved' or 'rejected'.
            approver_id: The user making the decision.
            comments: Optional comments / rejection feedback.

        Returns:
            The updated Approval record.

        Raises:
            ValueError: If the approval is not found, already decided, or the
                approver lacks the required role.
        """
        approval = db.query(Approval).filter(Approval.id == approval_id).first()
        if not approval:
            raise ValueError(f"Approval '{approval_id}' not found")

        if approval.status != "pending":
            raise ValueError(
                f"Approval '{approval_id}' already resolved with status '{approval.status}'"
            )

        # Enforce role-based permissions (Req 9.4)
        if not self._user_has_approval_role(db, approver_id, approval.to_roles):
            raise ValueError(
                f"User '{approver_id}' does not have a required role "
                f"({approval.to_roles}) to approve stage '{approval.step_name}'"
            )

        # Update approval record (Req 9.2)
        now = datetime.now()
        approval.decision = decision
        approval.status = decision  # 'approved' or 'rejected'
        approval.approved_by = approver_id
        approval.approved_at = now
        approval.comments = comments
        if decision == "rejected" and comments:
            approval.feedback = comments

        db.commit()
        db.refresh(approval)

        # Log to AuditTrail (Req 9.5, 20.2)
        audit_entry = AuditTrail(
            id=str(uuid.uuid4()),
            user_id=approver_id,
            action_type=f"approval_{decision}",
            resource_type="approval",
            resource_id=approval_id,
            details={
                "stage": approval.step_name,
                "decision": decision,
                "project_id": approval.project_id,
                "workflow_run_id": approval.workflow_run_id,
                "comments": comments,
                "approver_id": approver_id,
                "timestamp": now.isoformat(),
            },
            created_at=now,
        )
        db.add(audit_entry)
        db.commit()

        logger.info(
            "ApprovalAgent: recorded decision '%s' on approval %s by user %s",
            decision,
            approval_id,
            approver_id,
        )
        return approval

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _user_has_approval_role(
        db: Session, user_id: str, required_roles: Any
    ) -> bool:
        """Check whether a user holds at least one of the required roles (Req 9.4).

        Args:
            db: Database session.
            user_id: The user to check.
            required_roles: List of role names that can approve.

        Returns:
            True if the user has at least one matching role.
        """
        if not required_roles:
            return True

        role_names: List[str] = (
            required_roles if isinstance(required_roles, list) else [required_roles]
        )

        user_roles = (
            db.query(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .filter(UserRole.user_id == user_id)
            .all()
        )
        user_role_names = {r[0] for r in user_roles}
        return bool(user_role_names & set(role_names))

    @staticmethod
    def _get_target_roles_for_stage(stage: str) -> List[str]:
        """Return the roles that can approve a given stage.

        This provides sensible defaults; the orchestrator or API layer can
        override these when creating approval requests.
        """
        stage_role_map: Dict[str, List[str]] = {
            "idea": ["Product_Manager", "Admin"],
            "feature": ["Product_Manager", "Admin"],
            "story": ["Product_Manager", "Admin"],
            "architecture": ["Architect", "Admin"],
            "code": ["Developer", "Architect", "Admin"],
            "tests": ["Developer", "QA", "Admin"],
            "deploy": ["Admin", "Architect"],
        }
        return stage_role_map.get(stage.lower(), ["Admin"])

    @staticmethod
    def _apply_decision(state: Dict[str, Any], approval: Approval) -> Dict[str, Any]:
        """Apply a recorded decision to the workflow state.

        - Approved: clear approval_required so orchestrator proceeds (Req 5.3)
        - Rejected: attach feedback for stage re-run (Req 9.3, 5.4)
        """
        decision = approval.decision

        if decision == "approved":
            state["approval_required"] = False
            logger.info(
                "ApprovalAgent: stage '%s' approved by %s",
                approval.step_name,
                approval.approved_by,
            )
        elif decision == "rejected":
            state["approval_required"] = False
            state["rejection_feedback"] = approval.feedback or approval.comments or ""
            logger.info(
                "ApprovalAgent: stage '%s' rejected by %s — feedback: %s",
                approval.step_name,
                approval.approved_by,
                state["rejection_feedback"],
            )

        # Update approvals history in state
        approvals = state.get("approvals", [])
        for entry in approvals:
            if entry.get("approval_id") == approval.id:
                entry["status"] = decision
                entry["decided_at"] = (
                    approval.approved_at.isoformat() if approval.approved_at else None
                )
                entry["approver_id"] = approval.approved_by
                break
        else:
            approvals.append({
                "approval_id": approval.id,
                "stage": approval.step_name,
                "status": decision,
                "decided_at": (
                    approval.approved_at.isoformat() if approval.approved_at else None
                ),
                "approver_id": approval.approved_by,
            })
        state["approvals"] = approvals

        return state
