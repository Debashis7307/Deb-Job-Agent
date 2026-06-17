"""
main.py — Entry point for the Job Application AI Agent
Runs both the web dashboard (Flask) and the daily scheduler (APScheduler)

Usage:
  .\\venv\\Scripts\\python main.py              # Start dashboard + daily scheduler (10 PM)
  .\\venv\\Scripts\\python main.py --run-now    # Run agent immediately (live)
  .\\venv\\Scripts\\python main.py --dry-run    # Run immediately in test mode
  .\\venv\\Scripts\\python main.py --dashboard  # Start dashboard only
  .\\venv\\Scripts\\python main.py --test-email # Test email config
"""
import sys
import logging
import colorlog
import threading
from datetime import datetime
from pathlib import Path


def setup_logging():
    """Configure colorful logging to both console and file."""
    Path("logs").mkdir(exist_ok=True)
    
    log_formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s] %(name)s: %(message)s%(reset)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG": "cyan", "INFO": "green",
            "WARNING": "yellow", "ERROR": "red", "CRITICAL": "red,bg_white",
        }
    )
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)

    today = datetime.now().strftime("%Y-%m-%d")
    file_handler = logging.FileHandler(f"logs/agent_{today}.log", encoding="utf-8")
    file_handler.setFormatter(file_formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def run_agent(dry_run: bool = None):
    """Run the full job application agent workflow."""
    import config as cfg
    from agent.graph import build_job_agent_graph, get_initial_state

    logger = logging.getLogger(__name__)
    if dry_run is None:
        dry_run = cfg.DRY_RUN

    logger.info("=" * 60)
    logger.info(f"JOB AGENT STARTING — {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
    logger.info(f"Mode: {'[DRY RUN] Testing mode' if dry_run else '[LIVE] Applying for real!'}")
    logger.info(f"Max apply today: {cfg.MAX_APPLY_PER_DAY}")
    logger.info(f"Cold emails today: {cfg.MAX_EMAIL_PER_DAY}")
    logger.info(f"Applications email:  {cfg.GMAIL_ADDRESS}")
    logger.info(f"Summary email to:    {cfg.PERSONAL_EMAIL}")
    logger.info("=" * 60)

    start_time = datetime.now()

    try:
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
        return final_state

    except Exception as e:
        logger.critical(f"AGENT CRASHED: {e}", exc_info=True)
        raise


def start_dashboard():
    """Start the Flask web dashboard in a background thread."""
    import config as cfg
    import sys
    import os

    # Add dashboard dir to path
    sys.path.insert(0, str(Path("dashboard").absolute()))

    logger = logging.getLogger(__name__)

    def run_flask():
        # Import Flask app from dashboard
        dashboard_path = str(Path(__file__).parent / "dashboard")
        sys.path.insert(0, dashboard_path)
        from app import app
        app.run(
            host="0.0.0.0",
            port=cfg.DASHBOARD_PORT,
            debug=False,
            use_reloader=False,
            threaded=True,
        )

    flask_thread = threading.Thread(target=run_flask, name="FlaskDashboard", daemon=True)
    flask_thread.start()
    logger.info(f"Dashboard running at: http://localhost:{cfg.DASHBOARD_PORT}")
    return flask_thread


def start_scheduler():
    """Start APScheduler for daily 10 PM runs."""
    import config as cfg
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    import pytz

    logger = logging.getLogger(__name__)
    tz = pytz.timezone(cfg.TIMEZONE)

    scheduler = BlockingScheduler(timezone=tz)

    # ── Daily job agent run ────────────────────────────────────────────────
    scheduler.add_job(
        func=run_agent,
        trigger=CronTrigger(
            hour=cfg.SCHEDULE_HOUR,      # 22 = 10 PM
            minute=cfg.SCHEDULE_MINUTE,  # 0
            timezone=tz
        ),
        id="daily_job_agent",
        name="Debashis Daily Job Application Agent",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # ── 30-minute heartbeat — replaces per-minute DB init spam ────────────
    def _heartbeat():
        next_run = scheduler.get_job("daily_job_agent").next_run_time
        next_run_str = next_run.strftime("%Y-%m-%d %H:%M %Z") if next_run else "?"
        logger.info(
            f"✅ Job Agent is running | Next scheduled run: {next_run_str}"
        )

    scheduler.add_job(
        func=_heartbeat,
        trigger="interval",
        minutes=30,
        id="heartbeat",
        name="Agent Heartbeat",
        replace_existing=True,
    )

    logger.info("=" * 60)
    logger.info("SCHEDULER ACTIVE")
    logger.info(f"Agent runs daily at {cfg.SCHEDULE_HOUR:02d}:{cfg.SCHEDULE_MINUTE:02d} {cfg.TIMEZONE}")
    logger.info("Press Ctrl+C to stop everything")
    logger.info("=" * 60)

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Shutting down scheduler...")
        scheduler.shutdown()


if __name__ == "__main__":
    # Always use UTF-8 output on Windows
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    setup_logging()
    logger = logging.getLogger(__name__)
    args = sys.argv[1:]

    if "--run-now" in args:
        logger.info("Manual trigger: Running agent NOW (live mode)")
        run_agent(dry_run=False)

    elif "--dry-run" in args:
        logger.info("Manual trigger: Running agent in DRY RUN mode")
        run_agent(dry_run=True)

    elif "--test-email" in args:
        import config as cfg
        from tools.email_sender import EmailSender
        logger.info("Testing email configuration...")
        sender = EmailSender(cfg.GMAIL_ADDRESS, cfg.GMAIL_APP_PASSWORD, cfg.RESUME_PATH)
        
        # Test cold email (from careers mail)
        result1 = sender.send_cold_email(
            to_email=cfg.GMAIL_ADDRESS,
            subject="[TEST] Job Agent Cold Email Test",
            body=f"Hi Debashis,\n\nThis is a test of the cold email system from your job-specific Gmail.\nResume should be attached!\n\n- Job Agent",
            dry_run=False,
        )
        
        # Test summary email (to personal mail)
        result2 = sender.send_summary_email(
            to_email=cfg.PERSONAL_EMAIL,
            subject="[TEST] Job Agent — Summary Email Test",
            html_body="<h1>Test Summary Email</h1><p>This confirms your personal email receives daily reports.</p>",
            dry_run=False,
        )
        
        if result1 and result2:
            logger.info(f"Both emails sent successfully!")
            logger.info(f"  Cold email → {cfg.GMAIL_ADDRESS}")
            logger.info(f"  Summary   → {cfg.PERSONAL_EMAIL}")
        else:
            logger.error("Email test failed. Check your Gmail App Password.")

    elif "--dashboard" in args:
        # Dashboard only (no scheduler)
        import config as cfg
        logger.info(f"Starting dashboard only at http://localhost:{cfg.DASHBOARD_PORT}")
        # Run Flask directly (blocking)
        sys.path.insert(0, str(Path("dashboard").absolute()))
        from dashboard.app import app
        app.run(host="0.0.0.0", port=cfg.DASHBOARD_PORT, debug=False, use_reloader=False)

    else:
        # DEFAULT: Start both dashboard + scheduler
        import config as cfg
        logger.info("Starting Job Agent (Dashboard + Daily Scheduler)")
        logger.info(f"Dashboard → http://localhost:{cfg.DASHBOARD_PORT}")
        
        # Start Flask in background thread
        start_dashboard()
        
        # Start scheduler (blocking — keeps the process alive)
        start_scheduler()
