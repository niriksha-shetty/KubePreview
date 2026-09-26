import asyncio
from datetime import datetime, timezone
import logging
from typing import Optional

from config import settings
import formatter
import github_client
import k8s_manager

logger = logging.getLogger("kubepreview.reaper")

_reaper_task: Optional[asyncio.Task] = None


def parse_iso_datetime(dt_str: str) -> Optional[datetime]:
    """Parse ISO 8601 datetime string into timezone-aware UTC datetime."""
    try:
        clean_str = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception as err:
        logger.warning("Failed to parse ISO datetime string '%s': %s", dt_str, err)
        return None


async def check_and_reap_expired_environments() -> int:
    """Check all managed namespaces and teardown any exceeding their TTL limit."""
    reaped_count = 0
    now_utc = datetime.now(timezone.utc)

    try:
        namespaces = await k8s_manager.list_managed_namespaces()
    except Exception as err:
        logger.error("[REAPER] Error querying Kubernetes namespaces: %s", err)
        return 0

    for ns in namespaces:
        pr_number = ns.get("pr_number")
        if not pr_number:
            continue

        created_at_str = ns.get("created_at")
        ttl_hours = float(ns.get("ttl_hours", settings.TTL_HOURS))
        repo_full_name = ns.get("repo_full_name", "acme/sample-app")

        created_dt: Optional[datetime] = None
        if created_at_str:
            created_dt = parse_iso_datetime(created_at_str)

        # Fallback to Kubernetes namespace creationTimestamp if annotation is missing
        if not created_dt and ns.get("creation_timestamp"):
            ts = ns["creation_timestamp"]
            if isinstance(ts, datetime):
                created_dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            elif isinstance(ts, str):
                created_dt = parse_iso_datetime(ts)

        if not created_dt:
            logger.warning("[REAPER] Namespace 'pr-%d' missing creation timestamp. Skipping.", pr_number)
            continue

        age_seconds = (now_utc - created_dt).total_seconds()
        ttl_seconds = ttl_hours * 3600.0

        if age_seconds > ttl_seconds:
            logger.info(
                "[REAPER] Environment for PR #%d (Age: %.2f hours, TTL: %.2f hours) has expired. Purging...",
                pr_number,
                age_seconds / 3600.0,
                ttl_hours,
            )
            try:
                # 1. Teardown preview environment
                await k8s_manager.teardown_preview_environment(pr_number)

                # 2. Update PR comment on GitHub
                expired_comment = formatter.generate_expired_comment(pr_number)
                await github_client.post_or_update_pr_comment(
                    repo_full_name=repo_full_name,
                    pr_number=pr_number,
                    comment_body=expired_comment,
                )

                logger.info("[REAPER] Purged expired environment for PR #%d", pr_number)
                reaped_count += 1
            except Exception as err:
                logger.error("[REAPER] Failed to purge expired environment for PR #%d: %s", pr_number, err)

    return reaped_count


async def _reaper_loop() -> None:
    """Continuous async background task loop for TTL Reaper Daemon."""
    logger.info("TTL Reaper Daemon active. Interval: %d seconds.", settings.REAPER_INTERVAL_SECONDS)
    while True:
        try:
            await check_and_reap_expired_environments()
        except asyncio.CancelledError:
            logger.info("TTL Reaper Daemon task received cancellation signal.")
            break
        except Exception as err:
            logger.error("Unexpected error in TTL Reaper loop: %s", err)

        try:
            await asyncio.sleep(settings.REAPER_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("TTL Reaper Daemon sleep interrupted. Exiting.")
            break


async def start_ttl_reaper(app=None) -> asyncio.Task:
    """Start the TTL Reaper Daemon task."""
    global _reaper_task
    if _reaper_task is None or _reaper_task.done():
        _reaper_task = asyncio.create_task(_reaper_loop(), name="ttl_reaper_daemon")
        logger.info("Started TTL Reaper Daemon background task.")
    return _reaper_task


async def stop_ttl_reaper() -> None:
    """Stop the TTL Reaper Daemon task on server shutdown."""
    global _reaper_task
    if _reaper_task and not _reaper_task.done():
        logger.info("Stopping TTL Reaper Daemon background task...")
        _reaper_task.cancel()
        try:
            await _reaper_task
        except asyncio.CancelledError:
            pass
        logger.info("TTL Reaper Daemon stopped.")
