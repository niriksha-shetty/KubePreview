import logging
import sys
from typing import Any, Dict, Optional
import httpx

from config import settings

logger = logging.getLogger("kubepreview.github_client")

COMMENT_MARKER = "<!-- kubepreview-bot-comment -->"
GITHUB_API_BASE_URL = "https://api.github.com"


def is_mock_mode() -> bool:
    """Check if GitHub API client operates in mock output mode."""
    token = settings.GITHUB_TOKEN
    if not token or token.strip().lower() in ("", "mock", "none", "false"):
        return True
    return False


async def post_or_update_pr_comment(
    repo_full_name: str,
    pr_number: int,
    comment_body: str,
) -> Optional[Dict[str, Any]]:
    """Post a new PR comment or update an existing comment containing the KubePreview marker.

    If GITHUB_TOKEN is 'mock' or unconfigured, logs the comment to stdout instead of calling API.
    """
    if is_mock_mode():
        logger.info(
            "[GITHUB MOCK CLIENT] Outputting PR comment for repo '%s' PR #%d (GITHUB_TOKEN='%s').",
            repo_full_name,
            pr_number,
            settings.GITHUB_TOKEN,
        )
        out_encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_body = comment_body.encode(out_encoding, errors="replace").decode(out_encoding)
        print("\n==================== [GITHUB MOCK PR COMMENT] ====================")
        print(f" Target Repo: {repo_full_name} | PR #{pr_number}")
        print("------------------------------------------------------------------")
        print(safe_body)
        print("==================================================================\n")
        return {"status": "mock", "repo": repo_full_name, "pr_number": pr_number}

    headers = {
        "Authorization": f"Bearer {settings.GITHUB_TOKEN.strip()}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "KubePreview-Bot/1.0",
    }

    comments_endpoint = f"/repos/{repo_full_name}/issues/{pr_number}/comments"

    async with httpx.AsyncClient(base_url=GITHUB_API_BASE_URL, headers=headers, timeout=10.0) as client:
        try:
            # 1. Fetch existing PR comments
            logger.info("Fetching PR comments from GitHub: GET %s", comments_endpoint)
            response = await client.get(comments_endpoint)

            if response.status_code == 404:
                logger.error("GitHub repository or PR not found: %s #%d", repo_full_name, pr_number)
                return None
            elif response.status_code in (403, 429):
                logger.warning(
                    "GitHub API rate limit or authorization error (HTTP %d): %s",
                    response.status_code,
                    response.text,
                )
                return None

            response.raise_for_status()
            comments = response.json()

            # 2. Search for existing comment with marker
            existing_comment_id = None
            if isinstance(comments, list):
                for comment in comments:
                    body = comment.get("body", "")
                    if COMMENT_MARKER in body:
                        existing_comment_id = comment.get("id")
                        break

            # 3. Update existing comment or create new comment
            if existing_comment_id:
                patch_endpoint = f"/repos/{repo_full_name}/issues/comments/{existing_comment_id}"
                logger.info("Updating existing GitHub PR comment (ID: %s): PATCH %s", existing_comment_id, patch_endpoint)
                patch_resp = await client.patch(patch_endpoint, json={"body": comment_body})
                patch_resp.raise_for_status()
                logger.info("Successfully updated GitHub PR comment ID %s", existing_comment_id)
                return patch_resp.json()
            else:
                logger.info("Creating new GitHub PR comment: POST %s", comments_endpoint)
                post_resp = await client.post(comments_endpoint, json={"body": comment_body})
                post_resp.raise_for_status()
                new_comment = post_resp.json()
                logger.info("Successfully created GitHub PR comment ID %s", new_comment.get("id"))
                return new_comment

        except httpx.HTTPStatusError as err:
            logger.error("GitHub API returned error status: %s - Body: %s", err, err.response.text if err.response else "")
        except httpx.RequestError as err:
            logger.error("GitHub API network request error: %s", err)
        except Exception as err:
            logger.error("Unexpected error in post_or_update_pr_comment: %s", err)

        return None
