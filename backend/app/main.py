"""Main FastAPI application"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
from app.core.config import settings
from app.core.logger import logger
from app.core.database import init_db
from app.api.routers import sops, golden_path, integrations, health, auth, policies, tasks, notifications, intelligence, tenant_config, github_intelligence, wiki, analysis_config, portfolio, modernize
from app.core.auth import create_default_roles
from app.core.database import SessionLocal

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting Savi GPS...")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    
    # Initialize database
    init_db()
    logger.info("Database initialized")
    
    # Create default roles
    db = SessionLocal()
    try:
        create_default_roles(db)
        logger.info("Default roles initialized")
        
        # Load default policies
        from app.services.policy_loader_service import PolicyLoaderService
        policy_loader = PolicyLoaderService(db)
        policies = policy_loader.load_default_policies(tenant_id=None)
        logger.info(f"Loaded {len(policies)} default policies")
    finally:
        db.close()
    
    # Start background task worker
    from app.services.task_worker import start_worker, stop_worker
    from app.services.intelligence.index_worker import start_index_worker, stop_index_worker
    await start_worker()
    logger.info("Task worker started")
    await start_index_worker()
    logger.info("Intelligence index worker started")
    
    yield
    
    # Stop background task worker
    logger.info("Shutting down Savi GPS...")
    await stop_index_worker()
    logger.info("Intelligence index worker stopped")
    await stop_worker()
    logger.info("Task worker stopped")

# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="Multi-agent AI-powered service for Idea → Features → Stories → Architecture → Components → Scaffolding",
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list or ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(sops.router, prefix=settings.API_V1_PREFIX)
app.include_router(golden_path.router, prefix=settings.API_V1_PREFIX)
app.include_router(integrations.router, prefix=settings.API_V1_PREFIX)
app.include_router(policies.router, prefix=settings.API_V1_PREFIX)
app.include_router(tasks.router, prefix=settings.API_V1_PREFIX)
app.include_router(notifications.router, prefix=settings.API_V1_PREFIX)
app.include_router(intelligence.router, prefix=settings.API_V1_PREFIX)
app.include_router(wiki.router, prefix=settings.API_V1_PREFIX)
app.include_router(github_intelligence.router, prefix=settings.API_V1_PREFIX)
app.include_router(analysis_config.router, prefix=settings.API_V1_PREFIX)
app.include_router(tenant_config.router, prefix=settings.API_V1_PREFIX)
app.include_router(portfolio.router, prefix=settings.API_V1_PREFIX)
app.include_router(modernize.router, prefix=settings.API_V1_PREFIX)

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "endpoints": {
            "sops": f"{settings.API_V1_PREFIX}/sops",
            "golden_path": f"{settings.API_V1_PREFIX}/golden-path",
            "integrations": f"{settings.API_V1_PREFIX}/integrations",
            "health": "/health",
            "docs": "/docs"
        }
    }

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True if settings.ENVIRONMENT == "development" else False,
        log_level=settings.LOG_LEVEL.lower()
    )

