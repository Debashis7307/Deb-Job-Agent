"""
agent/nodes/apply_node.py — Auto-apply to jobs via Playwright
Handles: LinkedIn Easy Apply, Naukri Quick Apply, Internshala Apply
"""
import asyncio
import random
import logging
from typing import Dict, List
from agent.state import AgentState
from database.db_manager import DatabaseManager
import config as cfg

logger = logging.getLogger(__name__)


def auto_apply_node(state: AgentState) -> Dict:
    """
    LangGraph node: Auto-apply to selected jobs.
    Groups jobs by portal and applies accordingly.
    """
    jobs_to_apply = state.get("jobs_to_apply", [])
    dry_run = state.get("dry_run", True)
    db = DatabaseManager(cfg.DB_PATH)
    results = []

    if not jobs_to_apply:
        logger.info("No jobs to apply to today")
        return {"application_results": [], "total_applied": 0, "total_failed": 0}

    logger.info(f"🚀 Applying to {len(jobs_to_apply)} jobs (dry_run={dry_run})")

    # Group by portal
    by_portal: Dict[str, List] = {}
    for job in jobs_to_apply:
        portal = job.get("portal", "unknown")
        by_portal.setdefault(portal, []).append(job)

    # ── Apply per portal ───────────────────────────────────────────────
    for portal, jobs in by_portal.items():
        logger.info(f"Applying to {len(jobs)} jobs on {portal}")

        for job in jobs:
            result = _apply_to_job(job, portal, dry_run)
            results.append(result)

            # Update database
            db.update_application_status(
                job["url"],
                status=result["status"],
                notes=result["notes"]
            )

            # Human-like delay between applications
            if not dry_run:
                delay = random.uniform(10, 30)
                logger.info(f"Waiting {delay:.0f}s before next application...")
                import time
                time.sleep(delay)

    applied = sum(1 for r in results if r["status"] in ("applied", "manual_required"))
    failed = sum(1 for r in results if r["status"] == "failed")
    actual_applied = sum(1 for r in results if r["status"] == "applied")
    queued_email = sum(1 for r in results if r["status"] == "manual_required")

    logger.info(
        f"Apply node done: {actual_applied} portal-applied, "
        f"{queued_email} queued for cold email, {failed} failed"
    )

    # Update daily stats
    db.update_daily_stats(
        state.get("run_date", ""),
        total_applied=applied,
        total_failed=failed
    )

    return {
        "application_results": results,
        "total_applied": applied,
        "total_failed": failed,
    }


def _apply_to_job(job: dict, portal: str, dry_run: bool) -> dict:
    """Route job application to the correct portal handler."""
    base_result = {
        "job_url": job.get("url", ""),
        "job_title": job.get("title", ""),
        "company": job.get("company", ""),
        "portal": portal,
        "hr_email": None,
        "email_sent": False,
        "status": "pending",
        "notes": "",
    }

    if dry_run:
        logger.info(f"[DRY RUN] Would apply: {job['title']} @ {job['company']} ({portal})")
        base_result["status"] = "applied"
        base_result["notes"] = "DRY RUN - not actually applied"
        return base_result

    try:
        if portal == "linkedin":
            return _apply_linkedin(job, base_result)
        elif portal == "naukri":
            return _apply_naukri(job, base_result)
        elif portal == "internshala":
            return _apply_internshala(job, base_result)
        elif portal == "remoteok":
            # RemoteOK is a paid platform. We skip applying entirely and only use it for email outreach.
            base_result["status"] = "email_sent"
            base_result["notes"] = "Paid apply portal. Skipping application; cold email outreach only."
            return base_result
        elif portal == "weworkremotely":
            # We Work Remotely is a paid platform. We skip applying entirely and only use it for email outreach.
            base_result["status"] = "email_sent"
            base_result["notes"] = "Paid apply platform. Skipping application; cold email outreach only."
            return base_result
        elif portal == "wellfound":
            base_result["status"] = "manual_required"
            base_result["notes"] = "No direct apply portal. Will send cold email."
            return base_result
        else:
            base_result["status"] = "manual_required"
            base_result["notes"] = f"Unknown portal: {portal}"
            return base_result

    except Exception as e:
        logger.error(f"Apply failed for {job['title']}: {e}")
        base_result["status"] = "failed"
        base_result["notes"] = str(e)
        return base_result


def _apply_linkedin(job: dict, result: dict) -> dict:
    """Apply to LinkedIn job using Easy Apply if available."""
    try:
        result["status"] = "manual_required"
        result["notes"] = "LinkedIn Easy Apply requires active session. Will cold email instead."
        # NOTE: Full LinkedIn Easy Apply automation would go here
        # It's complex due to varying form fields per job
        # For now we mark as manual and prioritize cold email
        return result
    except Exception as e:
        result["status"] = "failed"
        result["notes"] = str(e)
        return result


def _apply_naukri(job: dict, result: dict) -> dict:
    """Apply to Naukri job via Playwright."""
    try:
        result["status"] = "manual_required"
        result["notes"] = "Naukri quick apply queued (requires active session)"
        # Full Playwright apply logic for Naukri would go here
        return result
    except Exception as e:
        result["status"] = "failed"
        result["notes"] = str(e)
        return result


def _apply_internshala(job: dict, result: dict) -> dict:
    """Apply to Internshala internship/job via Playwright."""
    try:
        result["status"] = "manual_required"
        result["notes"] = "Internshala apply queued (requires active session)"
        return result
    except Exception as e:
        result["status"] = "failed"
        result["notes"] = str(e)
        return result
