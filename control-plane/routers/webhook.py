import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status

from config import settings
import formatter
import github_client
import k8s_manager
from schemas import PullRequestEvent, WebhookResponse
from security import verify_signature

logger = logging.getLogger("kubepreview.router.webhook")
router = APIRouter(tags=["webhook"])


async def provision_and_notify_task(pr_number: int, image_tag: str, repo_full_name: str, commit_sha: str) -> None:
    """Background task wrapper: provisions preview environment and posts/updates GitHub PR comment."""
    try:
        logger.info("Executing provision background task for PR #%d...", pr_number)
        await k8s_manager.provision_preview_environment(pr_number, image_tag, repo_full_name)

        preview_url = f"http://pr-{pr_number}.{settings.BASE_DOMAIN}"
        comment_body = formatter.generate_success_comment(
            pr_number=pr_number,
            commit_sha=commit_sha,
            url=preview_url,
            ttl_hours=settings.TTL_HOURS,
        )

        logger.info("Dispatching success comment for PR #%d to GitHub client...", pr_number)
        await github_client.post_or_update_pr_comment(
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            comment_body=comment_body,
        )
    except Exception as err:
        logger.error("Error executing provision_and_notify_task for PR #%d: %s", pr_number, err)


async def teardown_and_notify_task(pr_number: int, repo_full_name: str) -> None:
    """Background task wrapper: tears down preview environment and posts/updates GitHub PR comment."""
    try:
        logger.info("Executing teardown background task for PR #%d...", pr_number)
        await k8s_manager.teardown_preview_environment(pr_number)

        comment_body = formatter.generate_teardown_comment(pr_number)

        logger.info("Dispatching teardown comment for PR #%d to GitHub client...", pr_number)
        await github_client.post_or_update_pr_comment(
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            comment_body=comment_body,
        )
    except Exception as err:
        logger.error("Error executing teardown_and_notify_task for PR #%d: %s", pr_number, err)


@router.post("/webhook", status_code=status.HTTP_200_OK, response_model=WebhookResponse)
async def handle_github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
):
    """Handle incoming GitHub Pull Request webhooks."""
    body_bytes = await request.body()

    # 1. Verify HMAC-SHA256 Signature
    if not verify_signature(body_bytes, settings.GITHUB_WEBHOOK_SECRET, x_hub_signature_256):
        logger.warning("Rejecting unauthorized webhook request due to invalid HMAC signature.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid HMAC signature",
        )

    # 2. Handle GitHub Ping Event
    if x_github_event == "ping":
        logger.info("GitHub ping event received successfully.")
        return WebhookResponse(
            status="success",
            pr_number=0,
            action="ping",
            message="Pong! Webhook active.",
        )

    # 3. Filter Event Type
    if x_github_event != "pull_request":
        logger.info("Ignoring non-pull_request event: %s", x_github_event)
        return WebhookResponse(
            status="ignored",
            pr_number=0,
            action=x_github_event or "unknown",
            message=f"Event '{x_github_event}' ignored. Only 'pull_request' events are handled.",
        )

    # 4. Parse Payload JSON
    try:
        payload_dict = json.loads(body_bytes.decode("utf-8"))
        event = PullRequestEvent.model_validate(payload_dict)
        pr_number = event.get_pr_number()
        action = event.action.lower()
        image_tag = event.get_image_tag()
        repo_full_name = event.get_repo_full_name()
        commit_sha = event.get_commit_sha()
    except Exception as err:
        logger.error("Failed to parse GitHub webhook payload: %s", err)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed GitHub payload: {err}",
        )

    logger.info("Received PR webhook: PR #%d, Action: '%s', Head SHA: '%s', Repo: '%s'", pr_number, action, commit_sha, repo_full_name)

    # 5. Evaluate PR Actions & Dispatch Non-Blocking Background Tasks
    if action in ["opened", "reopened", "synchronize"]:
        background_tasks.add_task(
            provision_and_notify_task,
            pr_number,
            image_tag,
            repo_full_name,
            commit_sha,
        )
        return WebhookResponse(
            status="processing",
            pr_number=pr_number,
            action=action,
            message=f"Queued provision task for PR #{pr_number} (image tag: {image_tag})",
        )

    elif action == "closed":
        background_tasks.add_task(
            teardown_and_notify_task,
            pr_number,
            repo_full_name,
        )
        return WebhookResponse(
            status="processing",
            pr_number=pr_number,
            action=action,
            message=f"Queued teardown task for PR #{pr_number}",
        )

    else:
        logger.info("PR #%d action '%s' ignored.", pr_number, action)
        return WebhookResponse(
            status="ignored",
            pr_number=pr_number,
            action=action,
            message=f"Action '{action}' does not trigger provisioning or teardown.",
        )
