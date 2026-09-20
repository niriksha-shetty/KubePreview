from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware

from config import settings
import k8s_manager
from routers import webhook

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("kubepreview.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager for startup and shutdown hooks."""
    logger.info("Starting KubePreview Control Plane Service...")
    logger.info("Loaded Configuration: BASE_DOMAIN=%s, CLUSTER_IN_CLUSTER=%s, TTL_HOURS=%s", settings.BASE_DOMAIN, settings.CLUSTER_IN_CLUSTER, settings.TTL_HOURS)

    # Initialize Kubernetes client config
    k8s_manager.init_k8s_client()

    yield

    logger.info("Shutting down KubePreview Control Plane Service...")


app = FastAPI(
    title="KubePreview Control Plane API",
    description="Automated Multi-Tenant Preview Environment Orchestrator on Kubernetes",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(webhook.router, prefix="/api/v1")


@app.get("/", status_code=status.HTTP_200_OK)
async def root():
    """Root health and service information endpoint."""
    return {
        "service": "KubePreview Control Plane",
        "status": "online",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health", status_code=status.HTTP_200_OK)
@app.get("/healthz", status_code=status.HTTP_200_OK)
async def health_check():
    """Liveness/Readiness health check endpoint."""
    return {
        "status": "healthy",
        "service": "kubepreview-control-plane",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
