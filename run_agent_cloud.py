"""
run_agent_cloud.py — Cloud-safe entry point for the Job Application Agent
Used by GitHub Actions to run the full agent without a local .env file.

All config comes from environment variables (set as GitHub Secrets).
Logs to stdout for GitHub Actions log viewer.
"""
import sys
import os
import logging
from datetime import datetime
from pathlib import Path


def setup_cloud_logging():
    """Configure logging for GitHub Actions (no color, stdout only)."""
    Path("logs").mkdir(exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    today = datetime.now().strftime("%Y-%m-%d")
    file_handler = logging.FileHandler(f"logs/agent_{today}.log", encoding="utf-8")
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def verify_cloud_env():
    """Verify all required environment variables are present."""
    required = [
        "GEMINI_API_KEY",
        "GMAIL_ADDRESS",
        "GMAIL_APP_PASSWORD",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"❌ Missing required env vars: {', '.join(missing)}")
        sys.exit(1)


def run_agent_cloud():
    """Run the full agent in cloud mode."""
    logger = logging.getLogger(__name__)

    dry_run_str = os.environ.get("DRY_RUN", "false").lower()
    dry_run = dry_run_str == "true"

    logger.info("=" * 60)
    logger.info("JOB AGENT — CLOUD RUN (GitHub Actions)")
    logger.info(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    logger.info(f"Mode: {'[DRY RUN] Testing' if dry_run else '[LIVE] Applying for real!'}")
    logger.info(f"Python: {sys.version}")
    logger.info("=" * 60)

    start_time = datetime.now()

    try:
        import config as cfg
        from agent.graph import build_job_agent_graph, get_initial_state

        logger.info(f"Max apply today:  {cfg.MAX_APPLY_PER_DAY}")
        logger.info(f"Cold emails today: {cfg.MAX_EMAIL_PER_DAY}")
        logger.info(f"Applications email: {cfg.GMAIL_ADDRESS}")
        logger.info(f"Summary email to:   {cfg.PERSONAL_EMAIL}")

        agent = build_job_agent_graph()
        initial_state = get_initial_state(dry_run=dry_run)
        final_state = agent.invoke(initial_state)

        elapsed = (datetime.now() - start_time).seconds
        logger.info("=" * 60)
        logger.info(f"AGENT RUN COMPLETE in {elapsed}s")
        logger.info(f"  Scraped:        {final_state.get('total_scraped', 0)} jobs")
        logger.info(f"  New:            {final_state.get('total_new', 0)} jobs")
        logger.info(f"  Applied:        {final_state.get('total_applied', 0)} jobs")
        logger.info(f"  Emailed (jobs): {final_state.get('total_emailed', 0)} HRs")
        logger.info(f"  PDF drip sent:  {final_state.get('pdf_emails_sent', 0)} HR contacts")
        logger.info(f"  Failed:         {final_state.get('total_failed', 0)}")
        logger.info("=" * 60)

        sys.exit(0)

    except Exception as e:
        logger.critical(f"AGENT CRASHED: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    setup_cloud_logging()
    verify_cloud_env()
    run_agent_cloud()
