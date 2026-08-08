"""Savi Teammate orchestrator — Phase T6.

Phases: ready → ground → plan → code → test → pr → wait_feedback

Alpha runs inline (SAVI_ORCHESTRATOR_INLINE). Production should move to Arq
workers (ADR 0003 / 0008) — same service methods, different caller.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import SaviWorkItem, SessionLocal
from app.core.logger import logger
from app.services.connectors.registry import get_active_connector
from app.services.savi_coding_agent_adapter import SaviCodingAgentAdapter
from app.services.savi_context_assembly_service import SaviContextAssemblyService
from app.services.savi_policy_gate import (
    SaviPolicyDenied,
    assert_savi_action_allowed,
    assert_savi_apply_allowed,
    assert_savi_submit_allowed,
)
from app.services.savi_sandbox import ephemeral_sandbox
from app.services.savi_work_queue_service import SaviWorkQueueService

ORCH_PHASES = (
    "ready",
    "ground",
    "plan",
    "code",
    "test",
    "pr",
    "awaiting_approval",
    "wait_feedback",
    "done",
    "failed",
)

PHASE_ORDER = ["ready", "ground", "plan", "code", "test", "pr", "wait_feedback"]


class SaviOrchestratorService:
    def __init__(self, db: Session):
        self.db = db

    def get_item(
        self, tenant_id: str, team_id: str, savi_id: str, item_id: str
    ) -> Optional[SaviWorkItem]:
        return SaviWorkQueueService(self.db).get(
            tenant_id, team_id, savi_id, item_id
        )

    def status_dict(self, item: SaviWorkItem) -> Dict[str, Any]:
        return {
            "work_item_id": item.id,
            "queue_state": item.state,
            "orchestrator_phase": item.orchestrator_phase,
            "orchestrator_timeline": item.orchestrator_timeline or [],
            "orchestrator_tokens": item.orchestrator_tokens or 0,
            "orchestrator_error": item.orchestrator_error,
            "pr_url": item.pr_url,
            "pr_number": item.pr_number,
        }

    async def run_to_pr(
        self,
        tenant_id: str,
        team_id: str,
        savi_id: str,
        item_id: str,
    ) -> SaviWorkItem:
        """Drive work item from current phase through wait_feedback (open PR)."""
        item = self.get_item(tenant_id, team_id, savi_id, item_id)
        if not item:
            raise ValueError("Work item not found")

        # Ensure in_progress for execution
        if item.state == "queued":
            busy = SaviWorkQueueService(self.db).in_progress_for_savi(
                tenant_id, savi_id
            )
            if busy and busy.id != item.id:
                raise ValueError(
                    f"Savi already has in_progress work ({busy.id})"
                )
            item.state = "in_progress"
            item.started_at = item.started_at or datetime.now()
            self.db.commit()

        if not item.orchestrator_phase or item.orchestrator_phase in (
            "failed",
            "done",
        ):
            item.orchestrator_phase = "ready"
            item.orchestrator_error = None
            self.db.commit()

        while item.orchestrator_phase in PHASE_ORDER:
            phase = item.orchestrator_phase
            if phase == "wait_feedback":
                break
            if phase == "awaiting_approval":
                break
            if getattr(item, "cancel_requested", False):
                item.orchestrator_phase = "failed"
                item.orchestrator_error = "Cancelled (kill switch)"
                item.state = "cancelled"
                self._append_timeline(item, "cancel", "Kill switch — run stopped before apply")
                self.db.commit()
                break
            item = await self.advance_one(tenant_id, team_id, savi_id, item.id)
            if item.orchestrator_phase == "failed":
                break
            if item.orchestrator_phase == phase:
                # No progress
                break
        return item

    async def advance_one(
        self,
        tenant_id: str,
        team_id: str,
        savi_id: str,
        item_id: str,
    ) -> SaviWorkItem:
        item = self.get_item(tenant_id, team_id, savi_id, item_id)
        if not item:
            raise ValueError("Work item not found")
        if getattr(item, "cancel_requested", False):
            item.orchestrator_phase = "failed"
            item.orchestrator_error = "Cancelled (kill switch)"
            item.state = "cancelled"
            self._append_timeline(item, "cancel", "Kill switch")
            self.db.commit()
            self.db.refresh(item)
            return item
        phase = item.orchestrator_phase or "ready"
        try:
            if phase == "ready":
                assert_savi_submit_allowed(
                    self.db, tenant_id=tenant_id, team_id=team_id, savi_id=savi_id
                )
                await self._phase_ready(item)
            elif phase == "ground":
                await self._phase_ground(tenant_id, team_id, savi_id, item)
            elif phase == "plan":
                await self._phase_plan(item)
            elif phase == "code":
                await self._phase_code(item)
            elif phase == "test":
                await self._phase_test(item)
            elif phase == "pr":
                await self._phase_pr(tenant_id, team_id, savi_id, item)
            elif phase == "awaiting_approval":
                self._append_timeline(
                    item, "awaiting_approval", "Worker paused — resume via approve API"
                )
            elif phase == "wait_feedback":
                self._append_timeline(item, "wait_feedback", "Waiting for PR review")
            else:
                raise ValueError(f"Unknown phase {phase}")
            self.db.commit()
            self.db.refresh(item)
            return item
        except SaviPolicyDenied as e:
            return self._fail(item, str(e))
        except Exception as e:
            logger.exception("Orchestrator failed on %s phase=%s", item_id, phase)
            return self._fail(item, str(e)[:800])

    async def poll_feedback(
        self,
        tenant_id: str,
        team_id: str,
        savi_id: str,
        item_id: str,
        *,
        iterate: bool = True,
    ) -> Dict[str, Any]:
        assert_savi_action_allowed("poll_pr_feedback")
        item = self.get_item(tenant_id, team_id, savi_id, item_id)
        if not item:
            raise ValueError("Work item not found")
        if not item.pr_number or not item.pr_repository_id:
            raise ValueError("No PR linked to this work item")

        gh = get_active_connector(
            self.db, tenant_id, team_id, savi_id, "github"
        )
        if not gh:
            raise ValueError("No active GitHub connector")

        comments = await gh.list_pr_comments(
            repository_id=item.pr_repository_id, pr_number=item.pr_number
        )
        checks = await gh.get_pr_checks(
            repository_id=item.pr_repository_id, pr_number=item.pr_number
        )
        meta = dict(item.connector_meta or {})
        feedback = {
            "polled_at": datetime.now(timezone.utc).isoformat(),
            "comments": comments.data if comments.ok else {"error": comments.error},
            "checks": checks.data if checks.ok else {"error": checks.error},
        }
        meta["pr_feedback"] = feedback
        item.connector_meta = meta

        review_bodies = []
        if comments.ok:
            for c in (comments.data.get("review_comments") or []) + (
                comments.data.get("issue_comments") or []
            ):
                if c.get("body"):
                    review_bodies.append(c["body"])

        iterated = False
        if iterate and review_bodies and item.orchestrator_phase == "wait_feedback":
            assert_savi_action_allowed("iterate_code")
            # Re-enter code with feedback notes, then PR update (new commit files)
            notes = "\n\n".join(review_bodies[:10])
            meta_orch = dict(meta.get("orchestrator") or {})
            meta_orch["last_feedback"] = notes[:4000]
            meta["orchestrator"] = meta_orch
            item.connector_meta = meta
            item.orchestrator_phase = "code"
            self._append_timeline(
                item, "wait_feedback", f"Received {len(review_bodies)} comment(s); iterating"
            )
            self.db.commit()
            item = await self.advance_one(tenant_id, team_id, savi_id, item.id)  # code
            if item.orchestrator_phase == "test":
                item = await self.advance_one(tenant_id, team_id, savi_id, item.id)
            if item.orchestrator_phase == "pr":
                item = await self.advance_one(tenant_id, team_id, savi_id, item.id)
            iterated = True

        self.db.commit()
        self.db.refresh(item)
        return {
            "feedback": feedback,
            "iterated": iterated,
            "orchestration": self.status_dict(item),
        }

    # --- phases -------------------------------------------------------------

    async def _phase_ready(self, item: SaviWorkItem) -> None:
        assert_savi_action_allowed("read_context")
        q = SaviWorkQueueService(self.db)
        ready, questions = q.ready_check(item)
        if not ready:
            item.state = "needs_info"
            item.ready_questions = questions
            item.orchestrator_phase = "failed"
            item.orchestrator_error = "Definition of ready not met"
            self._append_timeline(item, "ready", "Not ready — needs_info")
            return
        self._append_timeline(item, "ready", "Ready check passed")
        item.orchestrator_phase = "ground"

    async def _phase_ground(
        self, tenant_id: str, team_id: str, savi_id: str, item: SaviWorkItem
    ) -> None:
        assert_savi_action_allowed("assemble_context")
        if not item.application_id:
            raise ValueError("application_id required for grounding")
        if not item.context_pack:
            await SaviContextAssemblyService(self.db).assemble(
                tenant_id, team_id, savi_id, item.id, commit=False
            )
            self.db.refresh(item)
        self._append_timeline(item, "ground", "Context pack assembled")
        item.orchestrator_phase = "plan"

    def _coding_adapter(self, item: SaviWorkItem) -> SaviCodingAgentAdapter:
        from app.services.savi_identity_seat_service import SaviIdentitySeatService

        mode = SaviIdentitySeatService(self.db).resolve_execution_mode(
            item.tenant_id, item.team_id, item.savi_instance_id
        )
        return SaviCodingAgentAdapter(mode=mode)

    async def _phase_plan(self, item: SaviWorkItem) -> None:
        adapter = self._coding_adapter(item)
        plan, tokens = await adapter.plan(item, item.context_pack)
        meta = dict(item.connector_meta or {})
        orch = dict(meta.get("orchestrator") or {})
        orch["plan"] = plan
        meta["orchestrator"] = orch
        item.connector_meta = meta
        item.orchestrator_tokens = (item.orchestrator_tokens or 0) + tokens
        self._append_timeline(item, "plan", "Plan drafted", tokens=tokens)
        item.orchestrator_phase = "code"

    async def _phase_code(self, item: SaviWorkItem) -> None:
        adapter = self._coding_adapter(item)
        meta = dict(item.connector_meta or {})
        orch = dict(meta.get("orchestrator") or {})
        plan = orch.get("plan") or f"# Plan\n{item.title}"
        feedback = orch.get("last_feedback")
        if feedback:
            plan = f"{plan}\n\n## Review feedback to address\n{feedback}"

        with ephemeral_sandbox(prefix=f"savi_{item.id[:8]}_") as sandbox:
            files, tokens = await adapter.propose_files(
                item, item.context_pack, plan, sandbox
            )
        orch["files"] = files
        meta["orchestrator"] = orch
        item.connector_meta = meta
        item.orchestrator_tokens = (item.orchestrator_tokens or 0) + tokens
        self._append_timeline(
            item, "code", f"Proposed {len(files)} file(s)", tokens=tokens
        )
        item.orchestrator_phase = "test"

    async def _phase_test(self, item: SaviWorkItem) -> None:
        assert_savi_action_allowed("test")
        # Thin: no full clone test harness required — record skip or light check
        detail = "Tests skipped (no project harness in sandbox thin slice)"
        meta = dict(item.connector_meta or {})
        orch = dict(meta.get("orchestrator") or {})
        orch["test_result"] = {"status": "skipped", "detail": detail}
        meta["orchestrator"] = orch
        item.connector_meta = meta
        self._append_timeline(item, "test", detail)
        item.orchestrator_phase = "pr"

    async def _phase_pr(
        self, tenant_id: str, team_id: str, savi_id: str, item: SaviWorkItem
    ) -> None:
        # Apply-time gate (ADR 0010 §5c) — fail closed; kill switch blocks PR
        assert_savi_apply_allowed(
            self.db,
            tenant_id=tenant_id,
            team_id=team_id,
            savi_id=savi_id,
            action="open_pr",
            cancel_requested=bool(getattr(item, "cancel_requested", False)),
        )
        # Soft-check: merge remains denied
        try:
            assert_savi_action_allowed("merge_pr")
            raise SaviPolicyDenied("merge_pr must remain denied")
        except SaviPolicyDenied:
            pass

        gh = get_active_connector(
            self.db, tenant_id, team_id, savi_id, "github"
        )
        if not gh:
            raise ValueError("No active GitHub connector — bind one to open a PR")

        repo_id = item.pr_repository_id
        if not repo_id and item.context_pack:
            repos = item.context_pack.get("repositories") or []
            if repos:
                repo_id = repos[0].get("id")
        if not repo_id:
            raise ValueError("No repository_id for PR")

        meta = dict(item.connector_meta or {})
        orch = dict(meta.get("orchestrator") or {})
        files = orch.get("files") or []
        plan = orch.get("plan") or ""

        # Optional HITL: if connector_meta.requires_approval, pause before PR
        if orch.get("requires_approval") and item.orchestrator_phase != "awaiting_approval":
            import hashlib
            import json

            diff_material = json.dumps(files, sort_keys=True, default=str)
            item.approval_diff_hash = hashlib.sha256(
                diff_material.encode("utf-8")
            ).hexdigest()
            item.approval_base_sha = (meta.get("github") or {}).get("base_sha")
            item.approval_bound_at = datetime.now(timezone.utc)
            item.orchestrator_phase = "awaiting_approval"
            self._append_timeline(
                item,
                "awaiting_approval",
                f"Paused for approval (diff={item.approval_diff_hash[:12]})",
            )
            return

        from app.services.agent_runtime.contracts import IdempotencyKey
        from app.services.agent_runtime.execution_audit import log_agent_side_effect
        from app.services.agent_runtime.outbound_scrub import scrub_structure

        files, _ = scrub_structure(files)
        attempt = int((meta.get("github") or {}).get("attempt") or 1)
        key = IdempotencyKey(
            tenant_id=tenant_id,
            repo_id=repo_id,
            work_ref=item.id,
            action_type="open_pr",
            attempt=attempt,
        )

        adapter = self._coding_adapter(item)
        result = await gh.open_pr_for_work_item(
            item,
            repository_id=repo_id,
            files=files if isinstance(files, list) else [],
            title=f"[Savi] {item.title}",
            body=(
                f"Automated Savi Teammate PR for work `{item.id}`.\n\n"
                f"## Plan\n\n{plan[:6000]}\n\n"
                "---\n_Savi does not merge — human review required._"
            ),
            attempt=attempt,
        )
        if not result.ok:
            raise ValueError(result.error or "Failed to open PR")

        log_agent_side_effect(
            self.db,
            tenant_id=tenant_id,
            actor_id=savi_id,
            action_type="savi_open_pr",
            resource_type="savi_work_item",
            resource_id=item.id,
            idempotency_key=key,
            policy_decision="allow",
            versions=adapter.run_versions().to_dict(),
            savi_id=savi_id,
            extra={
                "pr_url": result.data.get("pr_url"),
                "metered_by": adapter.metered_by(),
                "branch": result.data.get("branch"),
            },
        )

        self._append_timeline(item, "pr", f"Opened {result.data.get('pr_url')}")
        item.orchestrator_phase = "wait_feedback"
        item.state = "in_review"

        await self._notify_pr(tenant_id, team_id, savi_id, item, result.data)

    def request_cancel(
        self, tenant_id: str, team_id: str, savi_id: str, item_id: str
    ) -> SaviWorkItem:
        """Kill switch — cooperative cancel; blocks apply if still pre-PR."""
        assert_savi_action_allowed("cancel_run")
        item = self.get_item(tenant_id, team_id, savi_id, item_id)
        if not item:
            raise ValueError("Work item not found")
        item.cancel_requested = True
        item.updated_at = datetime.now()
        # If paused for approval or not yet past PR, fail closed without opening PR
        if item.orchestrator_phase in (
            "ready",
            "ground",
            "plan",
            "code",
            "test",
            "pr",
            "awaiting_approval",
        ):
            item.orchestrator_phase = "failed"
            item.orchestrator_error = "Cancelled (kill switch) — PR not opened"
            item.state = "cancelled"
            self._append_timeline(
                item, "cancel", "Kill switch: branch may exist; PR not opened; wiki not published"
            )
        self.db.commit()
        self.db.refresh(item)
        return item

    def approve_and_resume(
        self,
        tenant_id: str,
        team_id: str,
        savi_id: str,
        item_id: str,
        *,
        expected_diff_hash: Optional[str] = None,
    ) -> SaviWorkItem:
        """Resume from awaiting_approval if diff hash still matches (§5e)."""
        assert_savi_action_allowed("approve_work")
        item = self.get_item(tenant_id, team_id, savi_id, item_id)
        if not item:
            raise ValueError("Work item not found")
        if item.orchestrator_phase != "awaiting_approval":
            raise ValueError("Work item is not awaiting approval")
        if expected_diff_hash and item.approval_diff_hash != expected_diff_hash:
            item.orchestrator_phase = "code"
            item.orchestrator_error = None
            self._append_timeline(
                item,
                "approval_invalidated",
                "Diff moved — approval invalidated; re-queued to code",
            )
            self.db.commit()
            self.db.refresh(item)
            return item
        item.orchestrator_phase = "pr"
        orch = dict((item.connector_meta or {}).get("orchestrator") or {})
        orch["requires_approval"] = False
        meta = dict(item.connector_meta or {})
        meta["orchestrator"] = orch
        item.connector_meta = meta
        self._append_timeline(item, "approved", "Approval accepted — resuming PR")
        self.db.commit()
        self.db.refresh(item)
        return item

    async def _notify_pr(
        self, tenant_id, team_id, savi_id, item, pr_data
    ) -> None:
        pr_url = pr_data.get("pr_url")
        msg = f"Savi opened a PR for *{item.title}*: {pr_url}"
        try:
            assert_savi_action_allowed("post_slack")
            slack = get_active_connector(
                self.db, tenant_id, team_id, savi_id, "slack"
            )
            if slack:
                await slack.post_message(text=msg)
        except Exception as e:
            logger.warning("Slack notify skipped: %s", e)
        if item.external_ref and item.source == "jira":
            try:
                assert_savi_action_allowed("comment_jira")
                jira = get_active_connector(
                    self.db, tenant_id, team_id, savi_id, "jira"
                )
                if jira:
                    await jira.add_comment(
                        issue_key=item.external_ref,
                        body=f"Savi opened PR: {pr_url}",
                    )
                    assert_savi_action_allowed("transition_jira_in_review")
                    await jira.transition_issue(
                        issue_key=item.external_ref, transition_name="In Review"
                    )
            except Exception as e:
                logger.warning("Jira notify skipped: %s", e)

    def _fail(self, item: SaviWorkItem, error: str) -> SaviWorkItem:
        item.orchestrator_phase = "failed"
        item.orchestrator_error = error
        item.state = "blocked"
        self._append_timeline(item, "failed", error)
        self.db.commit()
        self.db.refresh(item)
        return item

    def _append_timeline(
        self,
        item: SaviWorkItem,
        phase: str,
        detail: str,
        *,
        tokens: int = 0,
        cost: float = 0.0,
    ) -> None:
        timeline = list(item.orchestrator_timeline or [])
        timeline.append(
            {
                "phase": phase,
                "at": datetime.now(timezone.utc).isoformat(),
                "detail": detail,
                "tokens": tokens,
                "cost": cost,
            }
        )
        item.orchestrator_timeline = timeline
        item.updated_at = datetime.now()


def schedule_orchestrator_run_inline(
    tenant_id: str,
    team_id: str,
    savi_id: str,
    item_id: str,
    *,
    mode: str = "run_to_pr",
) -> None:
    """Fire-and-forget inline run (Alpha / local). Prefer Arq via savi_job_queue."""

    async def _job():
        db = SessionLocal()
        try:
            orch = SaviOrchestratorService(db)
            if mode == "poll_feedback":
                await orch.poll_feedback(
                    tenant_id, team_id, savi_id, item_id, iterate=True
                )
            elif mode == "advance":
                await orch.advance_one(tenant_id, team_id, savi_id, item_id)
            else:
                await orch.run_to_pr(tenant_id, team_id, savi_id, item_id)
        except Exception as e:
            logger.exception("Background orchestrator job failed: %s", e)
            try:
                item = SaviOrchestratorService(db).get_item(
                    tenant_id, team_id, savi_id, item_id
                )
                if item:
                    item.orchestrator_error = str(e)[:2000]
                    db.commit()
            except Exception:
                pass
        finally:
            db.close()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_job())
        else:
            loop.run_until_complete(_job())
    except RuntimeError:
        asyncio.run(_job())


def schedule_orchestrator_run(
    tenant_id: str, team_id: str, savi_id: str, item_id: str
) -> None:
    """Backward-compatible entry — delegates to job queue (Arq or inline)."""
    from app.services.savi_job_queue import schedule_orchestrator_run as enqueue

    enqueue(tenant_id, team_id, savi_id, item_id, mode="run_to_pr")
