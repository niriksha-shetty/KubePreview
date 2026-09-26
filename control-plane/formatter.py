"""Rich Markdown Comment Generator for KubePreview GitHub Feedback Loop."""

COMMENT_MARKER = "<!-- kubepreview-bot-comment -->"


def generate_success_comment(pr_number: int, commit_sha: str, url: str, ttl_hours: int) -> str:
    """Generate rich Markdown comment for successfully provisioned preview environments."""
    short_sha = commit_sha[:7] if commit_sha else "latest"
    return f"""{COMMENT_MARKER}
## 🚀 KubePreview Environment Ready!

Preview environment for PR **#{pr_number}** has been successfully provisioned and deployed.

| Setting | Value |
| :--- | :--- |
| **Status** | 🟢 **Ready** |
| **Preview URL** | [{url}]({url}) |
| **Commit SHA** | `{short_sha}` |
| **TTL Lifetime** | **{ttl_hours} Hours** |

> 💡 **Note**: This environment runs in isolated namespace `pr-{pr_number}` and will self-destruct automatically after **{ttl_hours} hours**.
"""


def generate_expired_comment(pr_number: int) -> str:
    """Generate Markdown comment for expired/reaped preview environments."""
    return f"""{COMMENT_MARKER}
## 🔴 KubePreview Environment Expired

Preview environment for PR **#{pr_number}** has expired and been cleaned up.

| Setting | Value |
| :--- | :--- |
| **Status** | 🔴 **Expired / Self-Destructed** |
| **Environment** | `pr-{pr_number}` |

> ℹ️ **Notice**: Namespace `pr-{pr_number}` exceeded its TTL lifetime and was automatically purged by the Reaper Daemon. Push a new commit or reopen the PR to trigger re-provisioning.
"""


def generate_teardown_comment(pr_number: int) -> str:
    """Generate Markdown comment for torn-down preview environments upon PR close."""
    return f"""{COMMENT_MARKER}
## ⚪ KubePreview Environment Terminated

Preview environment for PR **#{pr_number}** was terminated.

| Setting | Value |
| :--- | :--- |
| **Status** | ⚪ **Terminated on PR Close** |
| **Environment** | `pr-{pr_number}` |

> ℹ️ **Notice**: Pull request **#{pr_number}** was closed. Namespace `pr-{pr_number}` and all associated Kubernetes resources have been removed.
"""
