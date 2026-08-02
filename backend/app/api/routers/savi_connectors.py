"""Savi connector bindings + actions + inbound webhooks (Phase T5)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import User, get_db
from app.core.logger import logger
from app.services.connectors.base import CONNECTOR_TYPES
from app.services.connectors.binding_service import SaviConnectorBindingService
from app.services.connectors.registry import get_active_connector
from app.services.savi_work_queue_service import SaviWorkQueueService
from app.services.team_acl import require_savi_work_access, user_can_manage_teams

router = APIRouter(tags=["Savi Connectors"])


def _require_admin(user: User, db: Session) -> None:
    if not user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")
    if not user_can_manage_teams(user, db):
        raise HTTPException(status_code=403, detail="Admin permission required")


class BindingUpsertRequest(BaseModel):
    connector_type: str
    config: Optional[Dict[str, Any]] = None
    secret: Optional[str] = Field(
        None, description="API token / bot token (stored encrypted)"
    )
    clear_secret: bool = False
    status: str = "active"


class OpenPrRequest(BaseModel):
    repository_id: str
    title: Optional[str] = None
    body: Optional[str] = None
    files: Optional[List[Dict[str, str]]] = Field(
        None, description="[{path, content}] — default: context brief markdown"
    )


class JiraCommentRequest(BaseModel):
    body: str


class JiraTransitionRequest(BaseModel):
    transition_name: str = "In Review"


class SlackPostRequest(BaseModel):
    text: str
    thread_ts: Optional[str] = None


class ConfluenceFetchRequest(BaseModel):
    url: str


# --- Bindings CRUD ----------------------------------------------------------


@router.get("/teams/{team_id}/savi/{savi_id}/connectors")
async def list_connectors(
    team_id: str,
    savi_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_savi_work_access(db, user, team_id)
    svc = SaviConnectorBindingService(db)
    try:
        rows = svc.list_for_savi(user.tenant_id, team_id, savi_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "connectors": [svc.to_dict(r) for r in rows],
        "supported_types": list(CONNECTOR_TYPES),
    }


@router.put("/teams/{team_id}/savi/{savi_id}/connectors/{connector_type}")
async def upsert_connector(
    team_id: str,
    savi_id: str,
    connector_type: str,
    request: BindingUpsertRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(user, db)
    if connector_type != request.connector_type and request.connector_type:
        # path wins
        pass
    svc = SaviConnectorBindingService(db)
    try:
        binding = svc.upsert(
            user.tenant_id,
            team_id,
            savi_id,
            connector_type,
            config=request.config,
            secret=request.secret,
            clear_secret=request.clear_secret,
            status=request.status,
            created_by=user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return svc.to_dict(binding)


@router.post("/teams/{team_id}/savi/{savi_id}/connectors/{binding_id}/disable")
async def disable_connector(
    team_id: str,
    savi_id: str,
    binding_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(user, db)
    svc = SaviConnectorBindingService(db)
    binding = svc.get(user.tenant_id, binding_id)
    if not binding or binding.team_id != team_id or binding.savi_instance_id != savi_id:
        raise HTTPException(status_code=404, detail="Binding not found")
    try:
        binding = svc.disable(user.tenant_id, binding_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return svc.to_dict(binding)


# --- Actions ----------------------------------------------------------------


@router.post("/teams/{team_id}/savi/{savi_id}/work/{item_id}/open-pr")
async def open_work_pr(
    team_id: str,
    savi_id: str,
    item_id: str,
    request: OpenPrRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_savi_work_access(db, user, team_id)
    gh = get_active_connector(db, user.tenant_id, team_id, savi_id, "github")
    if not gh:
        raise HTTPException(
            status_code=400,
            detail="No active GitHub connector binding for this Savi",
        )
    q = SaviWorkQueueService(db)
    item = q.get(user.tenant_id, team_id, savi_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Work item not found")
    result = await gh.open_pr_for_work_item(
        item,
        repository_id=request.repository_id,
        files=request.files,
        title=request.title,
        body=request.body,
    )
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error or "PR failed")

    # Best-effort Slack + Jira notify
    await _notify_pr_opened(db, user.tenant_id, team_id, savi_id, item, result.data)

    return {"ok": True, "pr": result.data, "work_item": q.to_dict(item)}


class OrchestratorRunRequest(BaseModel):
    background: bool = Field(
        True,
        description=(
            "If true (default), enqueue via Arq when SAVI_USE_ARQ else inline. "
            "If false, run synchronously in the API request (local debug only)."
        ),
    )


class FeedbackPollRequest(BaseModel):
    iterate: bool = True


class ExternalIdentityRequest(BaseModel):
    provider: str = Field(..., description="entra | okta | google | github | custom")
    subject: str = Field(..., description="UPN, email, object id, or SP client id")
    display_name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class CodingAgentSeatRequest(BaseModel):
    agent_type: str = Field(
        ..., description="github_copilot | cursor | kiro | claude_code | custom"
    )
    execution_mode: str = Field(
        "cli",
        description=(
            "cli | claude_cli | copilot_cli | kiro_cli | api | "
            "remote_runner | llm | heuristic"
        ),
    )
    status: str = Field(
        "pending_license", description="pending_license | active | disabled"
    )
    external_seat_ref: Optional[str] = Field(
        None, description="Vendor seat id / licensed email / installation id"
    )
    config: Optional[Dict[str, Any]] = None
    secret: Optional[str] = None
    clear_secret: bool = False


@router.get("/teams/{team_id}/savi/{savi_id}/identity")
async def get_savi_identity(
    team_id: str,
    savi_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Machine identity + attached company identity + coding-agent seat (T7)."""
    require_savi_work_access(db, user, team_id)
    from app.services.savi_identity_seat_service import (
        AGENT_TYPES,
        EXECUTION_MODES,
        EXTERNAL_PROVIDERS,
        SaviIdentitySeatService,
    )
    from app.services.savi_roster_service import SaviRosterService

    roster = SaviRosterService(db)
    savi = roster.get(user.tenant_id, savi_id)
    if not savi or savi.team_id != team_id:
        raise HTTPException(status_code=404, detail="Savi not found")
    id_svc = SaviIdentitySeatService(db)
    seat = id_svc.get_seat(user.tenant_id, team_id, savi_id)
    return {
        "savi": roster.to_dict(savi),
        "external_identity": id_svc.external_identity_dict(savi),
        "coding_agent_seat": id_svc.seat_to_dict(seat) if seat else None,
        "options": {
            "providers": list(EXTERNAL_PROVIDERS),
            "agent_types": list(AGENT_TYPES),
            "execution_modes": list(EXECUTION_MODES),
        },
    }


@router.put("/teams/{team_id}/savi/{savi_id}/identity/external")
async def attach_external_identity(
    team_id: str,
    savi_id: str,
    request: ExternalIdentityRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Attach company service account / SP to this Savi's GPS machine identity."""
    _require_admin(user, db)
    from app.services.savi_identity_seat_service import SaviIdentitySeatService
    from app.services.savi_roster_service import SaviRosterService

    try:
        savi = SaviIdentitySeatService(db).attach_external_identity(
            user.tenant_id,
            team_id,
            savi_id,
            provider=request.provider,
            subject=request.subject,
            display_name=request.display_name,
            metadata=request.metadata,
            linked_by=user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SaviRosterService(db).to_dict(savi)


@router.delete("/teams/{team_id}/savi/{savi_id}/identity/external")
async def detach_external_identity(
    team_id: str,
    savi_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(user, db)
    from app.services.savi_identity_seat_service import SaviIdentitySeatService
    from app.services.savi_roster_service import SaviRosterService

    try:
        savi = SaviIdentitySeatService(db).detach_external_identity(
            user.tenant_id, team_id, savi_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SaviRosterService(db).to_dict(savi)


@router.put("/teams/{team_id}/savi/{savi_id}/coding-agent")
async def upsert_coding_agent_seat(
    team_id: str,
    savi_id: str,
    request: CodingAgentSeatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bind coding-agent seat (Copilot/Cursor/Kiro/Claude) to this Savi."""
    _require_admin(user, db)
    from app.services.savi_identity_seat_service import SaviIdentitySeatService

    id_svc = SaviIdentitySeatService(db)
    try:
        seat = id_svc.upsert_seat(
            user.tenant_id,
            team_id,
            savi_id,
            agent_type=request.agent_type,
            execution_mode=request.execution_mode,
            status=request.status,
            external_seat_ref=request.external_seat_ref,
            config=request.config,
            secret=request.secret,
            clear_secret=request.clear_secret,
            created_by=user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return id_svc.seat_to_dict(seat)


@router.post("/teams/{team_id}/savi/{savi_id}/coding-agent/disable")
async def disable_coding_agent_seat(
    team_id: str,
    savi_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(user, db)
    from app.services.savi_identity_seat_service import SaviIdentitySeatService

    id_svc = SaviIdentitySeatService(db)
    try:
        seat = id_svc.disable_seat(user.tenant_id, team_id, savi_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not seat:
        raise HTTPException(status_code=404, detail="No coding agent seat bound")
    return id_svc.seat_to_dict(seat)


@router.post("/teams/{team_id}/savi/{savi_id}/work/{item_id}/orchestrate")
async def orchestrate_work_item(
    team_id: str,
    savi_id: str,
    item_id: str,
    request: OrchestratorRunRequest = OrchestratorRunRequest(),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run Savi orchestrator through PR (ready→…→wait_feedback)."""
    require_savi_work_access(db, user, team_id)
    from app.services.savi_job_queue import enqueue_savi_orchestrate
    from app.services.savi_orchestrator_service import SaviOrchestratorService

    if request.background:
        try:
            queued = await enqueue_savi_orchestrate(
                user.tenant_id, team_id, savi_id, item_id, mode="run_to_pr"
            )
        except Exception as e:
            raise HTTPException(status_code=503, detail=str(e))
        item = SaviWorkQueueService(db).get(
            user.tenant_id, team_id, savi_id, item_id
        )
        if not item:
            raise HTTPException(status_code=404, detail="Work item not found")
        return {
            "scheduled": True,
            "queue": queued,
            "orchestration": SaviOrchestratorService(db).status_dict(item),
            "work_item": SaviWorkQueueService(db).to_dict(item),
        }

    orch = SaviOrchestratorService(db)
    try:
        item = await orch.run_to_pr(user.tenant_id, team_id, savi_id, item_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "scheduled": False,
        "orchestration": orch.status_dict(item),
        "work_item": SaviWorkQueueService(db).to_dict(item),
    }


@router.post("/teams/{team_id}/savi/{savi_id}/work/{item_id}/orchestrate/advance")
async def orchestrate_advance(
    team_id: str,
    savi_id: str,
    item_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_savi_work_access(db, user, team_id)
    from app.services.savi_orchestrator_service import SaviOrchestratorService

    orch = SaviOrchestratorService(db)
    try:
        item = await orch.advance_one(user.tenant_id, team_id, savi_id, item_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "orchestration": orch.status_dict(item),
        "work_item": SaviWorkQueueService(db).to_dict(item),
    }


@router.get("/teams/{team_id}/savi/{savi_id}/work/{item_id}/orchestration")
async def get_orchestration(
    team_id: str,
    savi_id: str,
    item_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_savi_work_access(db, user, team_id)
    from app.services.savi_orchestrator_service import SaviOrchestratorService

    orch = SaviOrchestratorService(db)
    item = orch.get_item(user.tenant_id, team_id, savi_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Work item not found")
    return orch.status_dict(item)


@router.post("/teams/{team_id}/savi/{savi_id}/work/{item_id}/poll-feedback")
async def poll_pr_feedback(
    team_id: str,
    savi_id: str,
    item_id: str,
    request: FeedbackPollRequest = FeedbackPollRequest(),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_savi_work_access(db, user, team_id)
    from app.services.savi_orchestrator_service import SaviOrchestratorService

    orch = SaviOrchestratorService(db)
    try:
        result = await orch.poll_feedback(
            user.tenant_id,
            team_id,
            savi_id,
            item_id,
            iterate=request.iterate,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    item = orch.get_item(user.tenant_id, team_id, savi_id, item_id)
    return {
        **result,
        "work_item": SaviWorkQueueService(db).to_dict(item) if item else None,
    }


@router.get("/teams/{team_id}/savi/{savi_id}/work/{item_id}/pr-checks")
async def work_pr_checks(
    team_id: str,
    savi_id: str,
    item_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_savi_work_access(db, user, team_id)
    gh = get_active_connector(db, user.tenant_id, team_id, savi_id, "github")
    if not gh:
        raise HTTPException(status_code=400, detail="No active GitHub connector")
    item = SaviWorkQueueService(db).get(user.tenant_id, team_id, savi_id, item_id)
    if not item or not item.pr_number or not item.pr_repository_id:
        raise HTTPException(status_code=400, detail="Work item has no linked PR")
    result = await gh.get_pr_checks(
        repository_id=item.pr_repository_id, pr_number=item.pr_number
    )
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error)
    return result.data


@router.post("/teams/{team_id}/savi/{savi_id}/jira/comment")
async def jira_comment(
    team_id: str,
    savi_id: str,
    request: JiraCommentRequest,
    issue_key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_savi_work_access(db, user, team_id)
    jira = get_active_connector(db, user.tenant_id, team_id, savi_id, "jira")
    if not jira:
        raise HTTPException(status_code=400, detail="No active Jira connector")
    result = await jira.add_comment(issue_key=issue_key, body=request.body)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error)
    return result.data


@router.post("/teams/{team_id}/savi/{savi_id}/jira/transition")
async def jira_transition(
    team_id: str,
    savi_id: str,
    request: JiraTransitionRequest,
    issue_key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_savi_work_access(db, user, team_id)
    jira = get_active_connector(db, user.tenant_id, team_id, savi_id, "jira")
    if not jira:
        raise HTTPException(status_code=400, detail="No active Jira connector")
    result = await jira.transition_issue(
        issue_key=issue_key, transition_name=request.transition_name
    )
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error)
    return result.data


@router.post("/teams/{team_id}/savi/{savi_id}/slack/post")
async def slack_post(
    team_id: str,
    savi_id: str,
    request: SlackPostRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_savi_work_access(db, user, team_id)
    slack = get_active_connector(db, user.tenant_id, team_id, savi_id, "slack")
    if not slack:
        raise HTTPException(status_code=400, detail="No active Slack connector")
    result = await slack.post_message(text=request.text, thread_ts=request.thread_ts)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error)
    return {**result.data, "stubbed": result.stubbed}


@router.post("/teams/{team_id}/savi/{savi_id}/confluence/fetch")
async def confluence_fetch(
    team_id: str,
    savi_id: str,
    request: ConfluenceFetchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_savi_work_access(db, user, team_id)
    conf = get_active_connector(db, user.tenant_id, team_id, savi_id, "confluence")
    if not conf:
        raise HTTPException(status_code=400, detail="No active Confluence connector")
    result = await conf.fetch_page_by_url(url=request.url)
    if not result.ok and not result.stubbed:
        raise HTTPException(status_code=400, detail=result.error)
    return {**result.data, "stubbed": result.stubbed, "ok": result.ok}


# --- Inbound webhooks (no JWT; token on binding) -----------------------------


def _verify_webhook_token(binding, provided: Optional[str]) -> None:
    cfg = binding.config_json or {}
    expected = cfg.get("webhook_token") or settings.SAVI_WEBHOOK_SHARED_SECRET
    if not expected:
        raise HTTPException(
            status_code=503, detail="Webhook token not configured on binding"
        )
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook token")


@router.post("/webhooks/savi/{savi_id}/jira")
async def jira_assign_webhook(
    savi_id: str,
    request: Request,
    db: Session = Depends(get_db),
    x_savi_webhook_token: Optional[str] = Header(None),
    token: Optional[str] = None,
):
    """
    Jira automation/webhook → enqueue work on this Savi.
    Expect JSON with issue.key, issue.fields.summary, issue.fields.description.
    Auth: header X-Savi-Webhook-Token or ?token=
    """
    from app.core.database import SaviInstance

    savi = db.query(SaviInstance).filter(SaviInstance.id == savi_id).first()
    if not savi or savi.status != "active":
        raise HTTPException(status_code=404, detail="Savi not found")
    binding = SaviConnectorBindingService(db).get_active(
        savi.tenant_id, savi.team_id, savi_id, "jira"
    )
    if not binding:
        raise HTTPException(status_code=400, detail="Jira connector not bound")
    _verify_webhook_token(binding, x_savi_webhook_token or token)

    payload = await request.json()
    issue = payload.get("issue") or payload
    fields = issue.get("fields") or {}
    key = issue.get("key") or payload.get("issue_key")
    summary = fields.get("summary") or payload.get("summary") or f"Jira {key}"
    description = fields.get("description")
    if isinstance(description, dict):
        # ADF — stash raw stringified for portal readiness
        description = str(description)[:4000]
    if not key:
        raise HTTPException(status_code=400, detail="Missing issue key")

    cfg = binding.config_json or {}
    default_app = cfg.get("default_application_id")

    q = SaviWorkQueueService(db)
    try:
        item = q.enqueue(
            savi.tenant_id,
            savi.team_id,
            savi_id,
            title=summary,
            description=description if isinstance(description, str) else None,
            application_id=default_app,
            source="jira",
            external_ref=key,
            assigned_by=None,
            context_refs=[
                {
                    "type": "jira_text",
                    "label": key,
                    "value": f"{summary}\n\n{description or ''}",
                }
            ],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    from app.services.savi_context_assembly_service import SaviContextAssemblyService

    if item.state == "queued" and item.application_id:
        item = await SaviContextAssemblyService(db).assemble_if_queued(
            savi.tenant_id, savi.team_id, savi_id, item
        )

    logger.info("Jira webhook enqueued %s for Savi %s key=%s", item.id, savi_id, key)
    return {"enqueued": True, "work_item_id": item.id, "state": item.state}


@router.post("/webhooks/savi/{savi_id}/slack")
async def slack_mention_webhook(
    savi_id: str,
    request: Request,
    db: Session = Depends(get_db),
    x_savi_webhook_token: Optional[str] = Header(None),
    token: Optional[str] = None,
):
    """
    Slack Events API (or workflow) → enqueue from @mention text.
    Body: { text, user, channel, ts } or Slack event_callback envelope.
    """
    from app.core.database import SaviInstance

    savi = db.query(SaviInstance).filter(SaviInstance.id == savi_id).first()
    if not savi or savi.status != "active":
        raise HTTPException(status_code=404, detail="Savi not found")
    binding = SaviConnectorBindingService(db).get_active(
        savi.tenant_id, savi.team_id, savi_id, "slack"
    )
    if not binding:
        raise HTTPException(status_code=400, detail="Slack connector not bound")

    payload = await request.json()
    # Slack URL verification
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    _verify_webhook_token(binding, x_savi_webhook_token or token)

    event = payload.get("event") or payload
    text = (event.get("text") or payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Missing text")

    # Strip mention tokens like <@U123>
    import re

    clean = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    title = clean.split("\n")[0][:120] or "Slack mention"
    cfg = binding.config_json or {}
    default_app = cfg.get("default_application_id")

    q = SaviWorkQueueService(db)
    try:
        item = q.enqueue(
            savi.tenant_id,
            savi.team_id,
            savi_id,
            title=title,
            description=clean,
            application_id=default_app,
            source="slack",
            external_ref=event.get("ts") or payload.get("ts"),
            assigned_by=None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    from app.services.savi_context_assembly_service import SaviContextAssemblyService

    if item.state == "queued" and item.application_id:
        item = await SaviContextAssemblyService(db).assemble_if_queued(
            savi.tenant_id, savi.team_id, savi_id, item
        )

    return {"enqueued": True, "work_item_id": item.id, "state": item.state}


async def _notify_pr_opened(db, tenant_id, team_id, savi_id, item, pr_data) -> None:
    pr_url = pr_data.get("pr_url")
    msg = f"Savi opened a PR for *{item.title}*: {pr_url}"
    slack = get_active_connector(db, tenant_id, team_id, savi_id, "slack")
    if slack:
        await slack.post_message(text=msg)
    if item.external_ref and item.source == "jira":
        jira = get_active_connector(db, tenant_id, team_id, savi_id, "jira")
        if jira:
            await jira.add_comment(
                issue_key=item.external_ref,
                body=f"Savi opened PR: {pr_url}",
            )
            await jira.transition_issue(
                issue_key=item.external_ref, transition_name="In Review"
            )
