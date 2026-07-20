"""Portfolio (CTO/CIO) read-only API — estate health aggregation."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps.portfolio_deps import require_portfolio
from app.core.auth import get_current_user
from app.core.database import User, get_db
from app.services.portfolio.health_aggregator import build_health, build_summary

router = APIRouter(prefix="/portfolio", tags=["Portfolio"])


@router.get("/health")
async def portfolio_health(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Executive estate health — inventory, documentation, risk, modernization."""
    require_portfolio(user, db)
    return build_health(db, user.tenant_id)


@router.get("/summary")
async def portfolio_summary(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Compact payload for dashboard Portfolio card."""
    require_portfolio(user, db)
    return build_summary(db, user.tenant_id)
