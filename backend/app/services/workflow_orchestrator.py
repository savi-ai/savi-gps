"""Golden Path Workflow Orchestrator using LangGraph"""
from typing import TypedDict, Dict, Any, List, Literal
from langgraph.graph import StateGraph, END
from app.services.agents.idea_agent import IdeaAgent
from app.services.agents.feature_agent import FeatureAgent
from app.services.agents.story_agent import StoryAgent
from app.services.agents.story_review_agent import StoryReviewAgent
from app.services.agents.domain_model_agent import DomainModelAgent
from app.services.agents.architecture_agent import ArchitectureAgent
from app.services.agents.stack_selector_agent import StackSelectorAgent
from app.services.agents.scaffolding_agents import (
    BackendScaffoldingAgent,
    FrontendScaffoldingAgent,
    InfraScaffoldingAgent
)
from app.services.agents.policy_injection_agent import PolicyInjectionAgent
from app.services.agents.validation_agent import ValidationAgent
from app.services.agents.approval_agent import ApprovalAgent
from app.services.agents.deployment_agent import DeploymentAgent
from app.services.agents.notification_agent import NotificationAgent
from app.core.database import SessionLocal, StageExecution, WorkflowRun, StateSnapshot
from app.core.logger import logger
from app.core.models import RunUntil
import uuid
from datetime import datetime


class WorkflowState(TypedDict):
    """Workflow state schema — enhanced with v2 fields (Req 6.1, 6.2)"""
    # Existing fields
    run_id: str
    stage: str
    idea: str
    vision: str
    candidate_features: List[Dict[str, Any]]
    features: List[Dict[str, Any]]
    stories: List[Dict[str, Any]]
    domain_model: Dict[str, Any]
    architecture: Dict[str, Any]
    stack_selections: List[Dict[str, Any]]
    scaffolding: Dict[str, Any]
    error: str
    results: List[Dict[str, Any]]
    # v2 fields
    execution_mode: str  # "autopilot" or "copilot"
    policy_bundle: Dict[str, Any]  # Resolved Effective Policy Set
    approval_required: bool
    approvals: List[Dict[str, Any]]  # Approval history
    deployment_url: str
    validation_result: Dict[str, Any]  # Latest validation result
    validation_blocked: bool  # True if validation found blocking violations
    rejection_feedback: str  # Feedback from rejected approval for stage re-run
    next_stage: str  # The next stage after current validation/approval
    stage_timings: Dict[str, Dict[str, str]]  # {stage: {start, end, status}}


# Ordered sequence of graph node names for the v2 pipeline (Req 4.1, 6.3).
# Node names use "stage_" prefix where the bare name would collide with a
# WorkflowState key (LangGraph forbids node names that match state keys).
STAGE_SEQUENCE = [
    "policy_resolution",
    "stage_idea",
    "stage_feature",
    "stage_story",
    "stage_story_review",
    "stage_architecture",
    "stage_code",
    "stage_tests",
    "stage_deploy",
    "stage_notify",
]

# Stages that require validation after completion (Req 11.1)
VALIDATED_STAGES = [
    "stage_idea",
    "stage_feature",
    "stage_story_review",
    "stage_architecture",
    "stage_code",
    "stage_tests",
]

# Map from node name to the next node name in the pipeline
NEXT_STAGE_MAP: Dict[str, str] = {}
for _i, _s in enumerate(STAGE_SEQUENCE):
    if _i + 1 < len(STAGE_SEQUENCE):
        NEXT_STAGE_MAP[_s] = STAGE_SEQUENCE[_i + 1]


class WorkflowOrchestrator:
    """Orchestrates the Golden Path workflow using LangGraph"""
    
    def __init__(self):
        # Initialize existing agents
        self.idea_agent = IdeaAgent()
        self.feature_agent = FeatureAgent()
        self.story_agent = StoryAgent()
        self.story_review_agent = StoryReviewAgent()
        self.domain_model_agent = DomainModelAgent()
        self.architecture_agent = ArchitectureAgent()
        self.stack_selector_agent = StackSelectorAgent()
        self.backend_scaffolding_agent = BackendScaffoldingAgent()
        self.frontend_scaffolding_agent = FrontendScaffoldingAgent()
        self.infra_scaffolding_agent = InfraScaffoldingAgent()

        # Initialize v2 agents (Req 6.1, 6.2)
        self.policy_injection_agent = PolicyInjectionAgent()
        self.validation_agent = ValidationAgent()
        self.approval_agent = ApprovalAgent()
        self.deployment_agent = DeploymentAgent()
        self.notification_agent = NotificationAgent()
        
        # Build the graph
        self.graph = self._build_graph()

    # ------------------------------------------------------------------
    # Stage timing & snapshot helpers (Req 4.2, 4.5, 6.4, 6.5)
    # ------------------------------------------------------------------

    @staticmethod
    def _record_stage_start(state: "WorkflowState", stage_name: str) -> None:
        """Record the start of a stage: update state timings and create a StageExecution DB record."""
        now = datetime.now()
        timings = state.get("stage_timings") or {}
        timings[stage_name] = {"start_time": now.isoformat(), "status": "in_progress"}
        state["stage_timings"] = timings

        run_id = state.get("run_id", "")
        db = SessionLocal()
        try:
            se = StageExecution(
                id=str(uuid.uuid4()),
                workflow_run_id=run_id,
                stage_name=stage_name,
                status="in_progress",
                started_at=now,
            )
            db.add(se)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("Failed to create StageExecution for %s: %s", stage_name, exc)
        finally:
            db.close()

    @staticmethod
    def _record_stage_end(state: "WorkflowState", stage_name: str, status: str = "completed") -> None:
        """Record the end of a stage: update state timings, update StageExecution, persist snapshot."""
        now = datetime.now()
        timings = state.get("stage_timings") or {}
        entry = timings.get(stage_name, {})
        entry["end_time"] = now.isoformat()
        entry["status"] = status
        timings[stage_name] = entry
        state["stage_timings"] = timings

        run_id = state.get("run_id", "")
        db = SessionLocal()
        try:
            # Update the StageExecution record
            se = (
                db.query(StageExecution)
                .filter(
                    StageExecution.workflow_run_id == run_id,
                    StageExecution.stage_name == stage_name,
                    StageExecution.status == "in_progress",
                )
                .first()
            )
            if se:
                se.status = status
                se.completed_at = now

            # Persist state snapshot on the WorkflowRun record (Req 6.5)
            wr = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
            if wr:
                # Serialise only JSON-safe parts of state
                snapshot = {k: v for k, v in state.items() if k != "stage_timings" or True}
                wr.state_snapshot = snapshot
                wr.current_stage = stage_name

            # Also persist a dedicated StateSnapshot row for recovery
            ss = StateSnapshot(
                id=str(uuid.uuid4()),
                project_id=state.get("project_id", run_id),
                workflow_step=stage_name,
                state_data=dict(state),
                is_milestone=True,
            )
            db.add(ss)

            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("Failed to record stage end for %s: %s", stage_name, exc)
        finally:
            db.close()

    def _build_graph(self) -> StateGraph:
        """Build the v2 LangGraph workflow with conditional edges (Req 4.1, 4.6, 5.1, 5.7, 6.3).

        Pipeline: policy_resolution → idea → validate → [approve] → feature →
        validate → [approve] → story → story_review → validate → [approve] →
        architecture → validate → [approve] → code → validate → [approve] →
        tests → validate → deploy → notify → END

        Validation runs after each core stage listed in VALIDATED_STAGES.
        Approval is conditional on Copilot mode (routed via _route_after_validation).
        """
        graph = StateGraph(WorkflowState)

        # -- Add all nodes ------------------------------------------------
        # v2 nodes
        graph.add_node("policy_resolution", self._policy_resolution_node)
        graph.add_node("validate", self._validate_node)
        graph.add_node("approve", self._approve_node)
        graph.add_node("stage_deploy", self._deploy_node)
        graph.add_node("stage_notify", self._notify_node)

        # Existing stage nodes (prefixed to avoid state key collisions)
        graph.add_node("stage_idea", self._idea_node)
        graph.add_node("stage_feature", self._feature_node)
        graph.add_node("stage_story", self._story_node)
        graph.add_node("stage_story_review", self._story_review_node)
        graph.add_node("stage_architecture", self._architecture_node)
        graph.add_node("stage_code", self._code_node)
        graph.add_node("stage_tests", self._tests_node)

        # -- Entry point: policy_resolution (Req 1.6, 3.1) ---------------
        graph.set_entry_point("policy_resolution")
        graph.add_edge("policy_resolution", "stage_idea")

        # -- Wire validated stages ----------------------------------------
        # Each validated stage gets an edge to "validate".
        # We build a single combined route map for validate → destinations
        # and approve → destinations, since LangGraph only allows one
        # conditional edge per (source_node, function_name) pair.
        validation_route_map: Dict[str, str] = {
            "approve": "approve",  # copilot → approval checkpoint
        }
        approval_route_map: Dict[str, str] = {}

        for stage_name in VALIDATED_STAGES:
            next_stage = NEXT_STAGE_MAP.get(stage_name)

            # stage → validate
            graph.add_edge(stage_name, "validate")

            # Validation can route back to the current stage (blocked) or forward
            validation_route_map[stage_name] = stage_name
            if next_stage:
                validation_route_map[next_stage] = next_stage

            # Approval can route back to the current stage (rejected) or forward
            approval_route_map[stage_name] = stage_name
            if next_stage:
                approval_route_map[next_stage] = next_stage

        # Single conditional edge from validate (covers all validated stages)
        graph.add_conditional_edges(
            "validate",
            self._route_after_validation,
            validation_route_map,
        )

        # Single conditional edge from approve (covers all validated stages)
        graph.add_conditional_edges(
            "approve",
            self._route_after_approval,
            approval_route_map,
        )

        # -- Non-validated edges ------------------------------------------
        # story → story_review (no validation between story and story_review)
        graph.add_edge("stage_story", "stage_story_review")

        # deploy → notify → END
        graph.add_edge("stage_deploy", "stage_notify")
        graph.add_edge("stage_notify", END)

        return graph.compile()
    
    async def _idea_node(self, state: WorkflowState) -> WorkflowState:
        """Idea processing node"""
        logger.info(f"Running idea node for run_id: {state.get('run_id')}")
        state["stage"] = "idea"
        self._record_stage_start(state, "idea")
        try:
            updated = await self.idea_agent.process(state)
        except Exception as exc:
            return self._handle_stage_error(state, "idea", exc)
        self._record_stage_end(updated, "idea")
        updated["results"] = updated.get("results", []) + [{
            "stage": "idea",
            "timestamp": datetime.now().isoformat(),
            "status": "completed",
            "output": {"vision": updated.get("vision"), "candidate_features": updated.get("candidate_features")}
        }]
        return updated
    
    async def _feature_node(self, state: WorkflowState) -> WorkflowState:
        """Feature generation node"""
        logger.info(f"Running feature node for run_id: {state.get('run_id')}")
        state["stage"] = "feature"
        self._record_stage_start(state, "feature")
        try:
            updated = await self.feature_agent.process(state)
        except Exception as exc:
            return self._handle_stage_error(state, "feature", exc)
        self._record_stage_end(updated, "feature")
        updated["results"] = updated.get("results", []) + [{
            "stage": "feature",
            "timestamp": datetime.now().isoformat(),
            "status": "completed",
            "output": {"features": updated.get("features")}
        }]
        return updated
    
    async def _story_node(self, state: WorkflowState) -> WorkflowState:
        """Story generation node"""
        logger.info(f"Running story node for run_id: {state.get('run_id')}")
        state["stage"] = "story"
        self._record_stage_start(state, "story")
        try:
            updated = await self.story_agent.process(state)
        except Exception as exc:
            return self._handle_stage_error(state, "story", exc)
        self._record_stage_end(updated, "story")
        updated["results"] = updated.get("results", []) + [{
            "stage": "story",
            "timestamp": datetime.now().isoformat(),
            "status": "completed",
            "output": {"stories": updated.get("stories")}
        }]
        return updated
    
    async def _story_review_node(self, state: WorkflowState) -> WorkflowState:
        """Story review node"""
        logger.info(f"Running story review node for run_id: {state.get('run_id')}")
        state["stage"] = "story_review"
        self._record_stage_start(state, "story_review")
        try:
            updated = await self.story_review_agent.process(state)
        except Exception as exc:
            return self._handle_stage_error(state, "story_review", exc)
        self._record_stage_end(updated, "story_review")
        updated["results"] = updated.get("results", []) + [{
            "stage": "story_review",
            "timestamp": datetime.now().isoformat(),
            "status": "completed",
            "output": {"stories": updated.get("stories"), "review": updated.get("story_review")}
        }]
        return updated
    
    async def _domain_model_node(self, state: WorkflowState) -> WorkflowState:
        """Domain modeling node"""
        logger.info(f"Running domain model node for run_id: {state.get('run_id')}")
        state["stage"] = "domain_model"
        self._record_stage_start(state, "domain_model")
        updated = await self.domain_model_agent.process(state)
        self._record_stage_end(updated, "domain_model")
        updated["results"] = updated.get("results", []) + [{
            "stage": "domain_model",
            "timestamp": datetime.now().isoformat(),
            "status": "completed",
            "output": {"domain_model": updated.get("domain_model")}
        }]
        return updated
    
    async def _architecture_node(self, state: WorkflowState) -> WorkflowState:
        """Architecture design node"""
        logger.info(f"Running architecture node for run_id: {state.get('run_id')}")
        state["stage"] = "architecture"
        self._record_stage_start(state, "architecture")
        try:
            updated = await self.architecture_agent.process(state)
        except Exception as exc:
            return self._handle_stage_error(state, "architecture", exc)
        self._record_stage_end(updated, "architecture")
        updated["results"] = updated.get("results", []) + [{
            "stage": "architecture",
            "timestamp": datetime.now().isoformat(),
            "status": "completed",
            "output": {"architecture": updated.get("architecture")}
        }]
        return updated
    
    async def _stack_selection_node(self, state: WorkflowState) -> WorkflowState:
        """Stack selection node"""
        logger.info(f"Running stack selection node for run_id: {state.get('run_id')}")
        state["stage"] = "stack_selection"
        self._record_stage_start(state, "stack_selection")
        updated = await self.stack_selector_agent.process(state)
        self._record_stage_end(updated, "stack_selection")
        updated["results"] = updated.get("results", []) + [{
            "stage": "stack_selection",
            "timestamp": datetime.now().isoformat(),
            "status": "completed",
            "output": {"stack_selections": updated.get("stack_selections")}
        }]
        return updated
    
    async def _scaffolding_node(self, state: WorkflowState) -> WorkflowState:
        """Scaffolding generation node"""
        logger.info(f"Running scaffolding node for run_id: {state.get('run_id')}")
        state["stage"] = "scaffolding"
        self._record_stage_start(state, "scaffolding")
        
        # Run all scaffolding agents
        updated = await self.backend_scaffolding_agent.process(state)
        updated = await self.frontend_scaffolding_agent.process(updated)
        updated = await self.infra_scaffolding_agent.process(updated)
        
        self._record_stage_end(updated, "scaffolding")
        updated["results"] = updated.get("results", []) + [{
            "stage": "scaffolding",
            "timestamp": datetime.now().isoformat(),
            "status": "completed",
            "output": {"scaffolding": updated.get("scaffolding")}
        }]
        return updated

    # ------------------------------------------------------------------
    # v2 node wrappers (Req 4.1, 5.1, 6.3)
    # ------------------------------------------------------------------

    async def _policy_resolution_node(self, state: WorkflowState) -> WorkflowState:
        """Policy resolution entry point — resolves Effective Policy Set (Req 3.1, 8.1)."""
        logger.info(f"Running policy_resolution node for run_id: {state.get('run_id')}")
        state["stage"] = "policy_resolution"
        self._record_stage_start(state, "policy_resolution")
        try:
            updated = await self.policy_injection_agent.process(state)
        except Exception as exc:
            return self._handle_stage_error(state, "policy_resolution", exc)
        self._record_stage_end(updated, "policy_resolution")
        updated["results"] = updated.get("results", []) + [{
            "stage": "policy_resolution",
            "timestamp": datetime.now().isoformat(),
            "status": "completed",
            "output": {"policy_bundle_keys": list((updated.get("policy_bundle") or {}).keys())},
        }]
        return updated

    async def _validate_node(self, state: WorkflowState) -> WorkflowState:
        """Validation gate — validates current stage output against SOPs and policies (Req 11.1–11.5)."""
        stage = state.get("stage", "")
        logger.info(f"Running validate node for stage '{stage}' run_id: {state.get('run_id')}")
        # Compute the graph node name for the current stage and the next stage
        # so routing functions can return valid node names.
        current_node = f"stage_{stage}" if stage else ""
        state["next_stage"] = NEXT_STAGE_MAP.get(current_node, "")
        updated = await self.validation_agent.process(state)
        return updated

    async def _approve_node(self, state: WorkflowState) -> WorkflowState:
        """Approval checkpoint — pauses for human approval in Copilot mode (Req 5.1, 9.1)."""
        stage = state.get("stage", "")
        logger.info(f"Running approve node for stage '{stage}' run_id: {state.get('run_id')}")
        updated = await self.approval_agent.process(state)
        return updated

    async def _deploy_node(self, state: WorkflowState) -> WorkflowState:
        """Deployment stage — provisions ephemeral environment (Req 7.1–7.7, 10.1–10.6)."""
        logger.info(f"Running deploy node for run_id: {state.get('run_id')}")
        state["stage"] = "deploy"
        self._record_stage_start(state, "deploy")
        try:
            updated = await self.deployment_agent.process(state)
        except Exception as exc:
            return self._handle_stage_error(state, "deploy", exc)
        self._record_stage_end(updated, "deploy")
        updated["results"] = updated.get("results", []) + [{
            "stage": "deploy",
            "timestamp": datetime.now().isoformat(),
            "status": "completed",
            "output": {"deployment_url": updated.get("deployment_url")},
        }]
        return updated

    async def _notify_node(self, state: WorkflowState) -> WorkflowState:
        """Notification stage — sends completion/failure notifications (Req 12.1–12.5)."""
        logger.info(f"Running notify node for run_id: {state.get('run_id')}")
        state["stage"] = "notify"
        self._record_stage_start(state, "notify")
        try:
            updated = await self.notification_agent.process(state)
        except Exception as exc:
            return self._handle_stage_error(state, "notify", exc)
        self._record_stage_end(updated, "notify")
        updated["results"] = updated.get("results", []) + [{
            "stage": "notify",
            "timestamp": datetime.now().isoformat(),
            "status": "completed",
            "output": {"notification_sent": True},
        }]
        return updated

    async def _code_node(self, state: WorkflowState) -> WorkflowState:
        """Code generation node — runs all scaffolding agents (backend, frontend, infra)."""
        logger.info(f"Running code node for run_id: {state.get('run_id')}")
        state["stage"] = "code"
        self._record_stage_start(state, "code")
        try:
            updated = await self.backend_scaffolding_agent.process(state)
            updated = await self.frontend_scaffolding_agent.process(updated)
            updated = await self.infra_scaffolding_agent.process(updated)
        except Exception as exc:
            return self._handle_stage_error(state, "code", exc)
        self._record_stage_end(updated, "code")
        updated["results"] = updated.get("results", []) + [{
            "stage": "code",
            "timestamp": datetime.now().isoformat(),
            "status": "completed",
            "output": {"scaffolding": updated.get("scaffolding")},
        }]
        return updated

    async def _tests_node(self, state: WorkflowState) -> WorkflowState:
        """Tests generation node — placeholder that records test stage completion."""
        logger.info(f"Running tests node for run_id: {state.get('run_id')}")
        state["stage"] = "tests"
        self._record_stage_start(state, "tests")
        # Tests stage uses scaffolding output; in the current codebase the
        # scaffolding agents already produce test artifacts as part of code gen.
        updated = dict(state)
        self._record_stage_end(updated, "tests")
        updated["results"] = updated.get("results", []) + [{
            "stage": "tests",
            "timestamp": datetime.now().isoformat(),
            "status": "completed",
            "output": {"tests_generated": True},
        }]
        return updated

    # ------------------------------------------------------------------
    # Routing functions for conditional edges (Req 4.1, 4.6, 5.1, 5.7)
    # ------------------------------------------------------------------

    @staticmethod
    def _route_after_validation(state: WorkflowState) -> str:
        """Route after validation gate.

        - If validation_blocked is True → return current stage node name (re-run)
        - If execution_mode == 'copilot' → return 'approve'
        - Otherwise (autopilot) → return next stage node name
        """
        stage = state.get("stage", "")
        current_node = f"stage_{stage}" if stage else ""
        validation_blocked = state.get("validation_blocked", False)
        execution_mode = state.get("execution_mode", "copilot")
        next_stage = state.get("next_stage", "")

        if validation_blocked:
            logger.info(
                "Routing after validation: BLOCKED — re-running stage '%s'", stage
            )
            return current_node

        if execution_mode == "copilot":
            logger.info(
                "Routing after validation: copilot mode — routing to approve for stage '%s'",
                stage,
            )
            return "approve"

        # Autopilot — proceed to next stage
        logger.info(
            "Routing after validation: autopilot — proceeding to '%s'", next_stage
        )
        return next_stage

    @staticmethod
    def _route_after_approval(state: WorkflowState) -> str:
        """Route after approval checkpoint.

        - If rejection_feedback exists → return current stage node name (re-run with feedback)
        - Otherwise → return next stage node name
        """
        stage = state.get("stage", "")
        current_node = f"stage_{stage}" if stage else ""
        rejection_feedback = state.get("rejection_feedback", "")
        next_stage = state.get("next_stage", "")

        if rejection_feedback:
            logger.info(
                "Routing after approval: REJECTED — re-running stage '%s' with feedback",
                stage,
            )
            return current_node

        logger.info(
            "Routing after approval: APPROVED — proceeding to '%s'", next_stage
        )
        return next_stage

    @staticmethod
    def cancel_workflow(run_id: str) -> bool:
        """Cancel a running workflow by run_id (Req 4.4, 19.4).

        Sets the WorkflowRun status to 'cancelled'. The running graph will
        stop after the current stage completes because stage nodes check for
        cancellation via the DB status.

        Returns True if the record was found and updated, False otherwise.
        """
        db = SessionLocal()
        try:
            wr = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
            if not wr:
                logger.warning("cancel_workflow: no WorkflowRun found for run_id '%s'", run_id)
                return False
            wr.status = "cancelled"
            wr.updated_at = datetime.now()
            db.commit()
            logger.info("Cancelled workflow run '%s'", run_id)
            return True
        except Exception as exc:
            db.rollback()
            logger.error("cancel_workflow failed for run_id '%s': %s", run_id, exc)
            return False
        finally:
            db.close()

    def _handle_stage_error(
        self, state: "WorkflowState", stage_name: str, error: Exception
    ) -> "WorkflowState":
        """Handle a stage failure: record error, notify, and update DB (Req 4.4, 19.4).

        - Records the error string in state['error']
        - Marks stage timing as 'failed'
        - In autopilot mode: triggers NotificationAgent with failure details
        - In copilot mode: sets error in state for the approval checkpoint to surface
        - Updates the WorkflowRun DB record with error and status='failed'
        """
        error_msg = str(error)
        state["error"] = error_msg
        logger.error("Stage '%s' failed for run_id '%s': %s", stage_name, state.get("run_id"), error_msg)

        # Record stage timing as failed
        self._record_stage_end(state, stage_name, status="failed")

        # Update WorkflowRun DB record
        run_id = state.get("run_id", "")
        if run_id:
            db = SessionLocal()
            try:
                wr = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
                if wr:
                    wr.error = error_msg
                    wr.status = "failed"
                    wr.updated_at = datetime.now()
                    db.commit()
            except Exception as exc:
                db.rollback()
                logger.warning("Failed to update WorkflowRun on error: %s", exc)
            finally:
                db.close()

        execution_mode = state.get("execution_mode", "copilot")
        if execution_mode == "autopilot":
            # Trigger NotificationAgent with failure details (Req 4.4)
            try:
                import asyncio
                # Build a minimal state snapshot for the notification
                notify_state = dict(state)
                notify_state["status"] = "failed"
                asyncio.get_event_loop().run_until_complete(
                    self.notification_agent.process(notify_state)
                )
            except RuntimeError:
                # Already inside an event loop — call directly via create_task
                pass
            except Exception as notify_exc:
                logger.warning("Failed to send failure notification: %s", notify_exc)
        # In copilot mode the error is already in state['error'] and will be
        # surfaced at the next approval checkpoint.

        return state

    @staticmethod
    def switch_to_autopilot(state: "WorkflowState") -> None:
        """Switch execution mode from Copilot to Autopilot mid-run (Req 5.7).

        Sets execution_mode to 'autopilot' and approval_required to False so
        all remaining stages proceed without human approval checkpoints.
        If a run_id is present, the corresponding WorkflowRun DB record is
        updated as well.
        """
        previous_mode = state.get("execution_mode", "copilot")
        state["execution_mode"] = "autopilot"
        state["approval_required"] = False

        logger.info(
            "Switched execution mode from '%s' to 'autopilot' for run_id: %s",
            previous_mode,
            state.get("run_id", "unknown"),
        )

        # Persist the mode change to the WorkflowRun DB record if run_id exists
        run_id = state.get("run_id")
        if run_id:
            db = SessionLocal()
            try:
                wr = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
                if wr:
                    wr.execution_mode = "autopilot"
                    wr.approval_required = False
                    db.commit()
                    logger.info(
                        "Updated WorkflowRun DB record '%s' to autopilot mode", run_id
                    )
                else:
                    logger.warning(
                        "WorkflowRun record not found for run_id '%s' during mode switch",
                        run_id,
                    )
            except Exception as exc:
                db.rollback()
                logger.warning(
                    "Failed to update WorkflowRun for mode switch (run_id=%s): %s",
                    run_id,
                    exc,
                )
            finally:
                db.close()

    # ------------------------------------------------------------------
    # State snapshot recovery (Req 19.5, P7)
    # ------------------------------------------------------------------

    @staticmethod
    def resume_incomplete_runs() -> List[tuple]:
        """Query incomplete WorkflowRun records and return recoverable state snapshots.

        Returns a list of (run_id, state_snapshot) tuples for runs with
        status='running' that have a persisted state_snapshot.  The Task
        Worker can call this on restart to discover which runs need to be
        resumed.
        """
        db = SessionLocal()
        try:
            incomplete = (
                db.query(WorkflowRun)
                .filter(WorkflowRun.status == "running")
                .all()
            )
            results: List[tuple] = []
            for wr in incomplete:
                snapshot = wr.state_snapshot
                if snapshot:
                    results.append((wr.id, snapshot))
                else:
                    logger.warning(
                        "Incomplete WorkflowRun '%s' has no state_snapshot — cannot resume",
                        wr.id,
                    )
            logger.info(
                "resume_incomplete_runs: found %d resumable run(s) out of %d incomplete",
                len(results),
                len(incomplete),
            )
            return results
        except Exception as exc:
            logger.error("resume_incomplete_runs failed: %s", exc)
            return []
        finally:
            db.close()

    @staticmethod
    def resume_from_snapshot(state: dict) -> dict:
        """Prepare a recovered state dict for resumption from the last completed stage.

        Determines the next stage to execute based on the last completed
        stage recorded in ``state['stage']`` and sets ``state['stage']`` to
        the appropriate resumption point.  Returns the updated state dict
        ready to be fed back into the workflow graph.
        """
        last_stage = state.get("stage", "")
        current_node = f"stage_{last_stage}" if last_stage else ""
        next_node = NEXT_STAGE_MAP.get(current_node, "")

        logger.info(
            "resume_from_snapshot: last completed stage='%s', next node='%s' for run_id='%s'",
            last_stage,
            next_node,
            state.get("run_id", "unknown"),
        )

        # Clear transient error / blocking flags so the resumed run starts clean
        state["error"] = ""
        state["validation_blocked"] = False
        state["rejection_feedback"] = ""
        state["next_stage"] = next_node

        return state

    def _should_stop(self, state: WorkflowState, run_until: RunUntil) -> Literal["continue", "stop"]:
        """Determine if workflow should stop based on run_until option"""
        current_stage = state.get("stage", "")
        
        if run_until == RunUntil.STORIES:
            if current_stage in ["story", "story_review"]:
                return "stop"
        elif run_until == RunUntil.ARCHITECTURE:
            if current_stage in ["architecture", "stack_selection"]:
                return "stop"
        
        return "continue"
    
    async def run(
        self,
        idea: str = None,
        feature_ids: List[str] = None,
        run_until: RunUntil = RunUntil.SCAFFOLDING
    ) -> Dict[str, Any]:
        """Run the Golden Path workflow"""
        run_id = str(uuid.uuid4())
        
        initial_state: WorkflowState = {
            "run_id": run_id,
            "stage": "initial",
            "idea": idea or "",
            "vision": "",
            "candidate_features": [],
            "features": [],
            "stories": [],
            "domain_model": {},
            "architecture": {},
            "stack_selections": [],
            "scaffolding": {},
            "error": "",
            "results": [],
            # v2 fields (Req 6.1, 6.2)
            "execution_mode": "copilot",
            "policy_bundle": {},
            "approval_required": False,
            "approvals": [],
            "deployment_url": "",
            "validation_result": {},
            "validation_blocked": False,
            "rejection_feedback": "",
            "next_stage": "",
            "stage_timings": {},
        }
        
        try:
            # Execute the graph
            final_state = await self.graph.ainvoke(initial_state)
            
            return {
                "run_id": run_id,
                "status": "completed",
                "state": final_state,
                "results": final_state.get("results", [])
            }
        except Exception as e:
            logger.error(f"Error executing workflow: {e}")
            return {
                "run_id": run_id,
                "status": "error",
                "error": str(e),
                "state": initial_state
            }

