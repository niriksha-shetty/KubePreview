from typing import List
from fastapi import APIRouter, status
from pydantic import BaseModel, Field

import k8s_manager

router = APIRouter(tags=["previews"])


class PreviewSandboxInfo(BaseModel):
    pr_number: int = Field(..., description="Pull Request number")
    namespace: str = Field(..., description="Kubernetes namespace name")
    created_at: str = Field(..., description="ISO 8601 creation timestamp")
    ttl_hours: float = Field(..., description="TTL lifetime in hours")
    remaining_minutes: int = Field(..., description="Remaining lifetime in minutes")
    status: str = Field(..., description="Status of preview environment ('Ready' or 'Provisioning')")
    preview_url: str = Field(..., description="Public HTTP preview access URL")


@router.get("/previews", status_code=status.HTTP_200_OK, response_model=List[PreviewSandboxInfo])
async def list_active_previews():
    """Retrieve telemetry for all active preview environments managed by KubePreview."""
    active_previews = await k8s_manager.get_active_previews_telemetry()
    return active_previews
