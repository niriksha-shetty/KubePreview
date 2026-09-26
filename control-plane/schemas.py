from typing import Optional
from pydantic import BaseModel, Field


class Repository(BaseModel):
    full_name: str = Field(..., description="Full repository name (e.g. acme/sample-app)")


class HeadRef(BaseModel):
    sha: str = Field("latest", description="Git commit SHA for pull request head")


class PullRequestDetail(BaseModel):
    number: int = Field(..., description="PR number")
    head: Optional[HeadRef] = Field(default_factory=HeadRef)


class PullRequestEvent(BaseModel):
    action: str = Field(..., description="PR event action (opened, closed, synchronize, etc.)")
    number: Optional[int] = Field(None, description="PR number at payload root level")
    pull_request: Optional[PullRequestDetail] = Field(None, description="PR detail object")
    repository: Optional[Repository] = Field(None, description="Repository information")

    def get_pr_number(self) -> int:
        if self.number is not None:
            return self.number
        if self.pull_request and self.pull_request.number is not None:
            return self.pull_request.number
        raise ValueError("PR number could not be determined from the webhook payload")

    def get_image_tag(self) -> str:
        if self.pull_request and self.pull_request.head and self.pull_request.head.sha:
            return self.pull_request.head.sha[:7]
        return "latest"

    def get_repo_full_name(self) -> str:
        if self.repository and self.repository.full_name:
            return self.repository.full_name
        return "acme/sample-app"

    def get_commit_sha(self) -> str:
        if self.pull_request and self.pull_request.head and self.pull_request.head.sha:
            return self.pull_request.head.sha
        return "latest"


class WebhookResponse(BaseModel):
    status: str
    pr_number: int
    action: str
    message: Optional[str] = None
