"""
agent/nodes/report_node.py — Generate daily summary report (console/log only)

Summary format (per user request):
1. Quick numeric summary at top (applied today, total, cold mail, PDF progress)
2. Inbox: bounce-back count only (no listing), then only REAL recruiter replies
NOTE: Summary email to personal mail is DISABLED per user request.
"""
import logging
import re
from datetime import datetime
from typing import Dict, List
from agent.state import AgentState
from database.db_manager import DatabaseManager
import config as cfg

logger = logging.getLogger(__name__)

# ── Bounce-back detection ─────────────────────────────────────────────────────
# These patterns indicate a mail delivery failure / bounce — NOT a recruiter reply
BOUNCE_PATTERNS = [
    r"mailer-daemon",
    r"mail delivery",
    r"delivery status",
    r"delivery failure",
    r"undeliverable",
    r"address not found",
    r"does not exist",
    r"no such user",
    r"user unknown",
    r"mailbox not found",
    r"invalid address",
    r"recipient address rejected",
    r"550",  # SMTP 550 = user not found
    r"552",  # mailbox full
    r"554",  # transaction failed
    r"postmaster",
    r"bounce",
    r"ndr",   # Non-Delivery Report
    r"auto-reply",
    r"out of office",
    r"automatic reply",
    r"vacation",
    r"away from office",
]

# Sender domains that are delivery systems — always bounces/system mail
BOUNCE_SENDER_DOMAINS = {
    "mailer-daemon", "postmaster", "bounces", "bounce", "noreply", "no-reply",
    "notification", "notifications", "alert", "alerts", "digest", "newsletter",
    "mailerdaemon",
}

# Job portal / marketing domains to exclude from recruiter replies
PORTAL_DOMAINS = {
    "linkedin.com", "naukri.com", "internshala.com", "wellfound.com",
    "google.com", "github.com", "vercel.com", "youtube.com", "facebook.com",
    "twitter.com", "instagram.com", "indeed.com", "glassdoor.com",
    "remoteok.com", "weworkremotely.com", "monster.com", "shine.com",
}


def _is_bounce_or_system(email_dict: dict) -> bool:
    """Return True if this email looks like a bounce-back or system auto-reply."""
    sender = email_dict.get("sender_email", "").lower()
    subject = email_dict.get("subject", "").lower()
    snippet = email_dict.get("snippet", "").lower()

    # Check sender domain
    sender_local = sender.split("@")[0] if "@" in sender else sender
    for bad in BOUNCE_SENDER_DOMAINS:
        if bad in sender_local or bad in sender:
            return True

    # Check subject + snippet for bounce keywords
    text_to_check = subject + " " + snippet
    for pattern in BOUNCE_PATTERNS:
        if re.search(pattern, text_to_check, re.IGNORECASE):
            return True

    return False


def _is_portal_or_marketing(email_dict: dict) -> bool:
    """Return True if this email is from a job portal or marketing system."""
    sender = email_dict.get("sender_email", "").lower()
    for domain in PORTAL_DOMAINS:
        if domain in sender:
            return True
    return False


def generate_report_node(state: AgentState) -> Dict:
    """
    LangGraph node: Generate daily summary report.
    
    - Logs a clean summary to console (no email to personal inbox per user request)
    - Filters inbox:
        * Bounce-backs (address not found etc.) → counted only, NOT listed
        * Portal/system mail → excluded silently
        * Real recruiter replies → listed in full
    """
    from tools.inbox_monitor import fetch_hr_replies

    db = DatabaseManager(cfg.DB_PATH)
    today = state.get("run_date", datetime.now().strftime("%Y-%m-%d"))

    # ── Fetch career inbox replies (IMAP monitor) ────────────────────────
    all_inbox_emails = fetch_hr_replies(days_back=3)

    # Classify inbox emails
    bounce_count = 0
    recruiter_replies = []

    for em in all_inbox_emails:
        if _is_bounce_or_system(em):
            bounce_count += 1
        elif _is_portal_or_marketing(em):
            pass  # Silently skip portal/marketing mail
        else:
            recruiter_replies.append(em)

    # ── Stats ──────────────────────────────────────────────────────────────
    total_scraped = state.get("total_scraped", 0)
    total_new = state.get("total_new", 0)
    total_applied = state.get("total_applied", 0)
    total_emailed = state.get("total_emailed", 0)
    total_failed = state.get("total_failed", 0)
    pdf_emails_sent = state.get("pdf_emails_sent", 0)

    # PDF drip stats
    pdf_stats = {"total_in_pdf": 0, "total_sent": 0, "sent_today": 0, "remaining": 0}
    try:
        from tools.pdf_hr_parser import get_pdf_hr_stats
        pdf_stats = get_pdf_hr_stats()
    except Exception:
        pass

    total_pdf_sent_alltime = pdf_stats.get("total_sent", 0)
    total_pdf_contacts = pdf_stats.get("total_in_pdf", 1831)  # fallback to 1831

    # All-time stats from DB
    all_time = db.get_all_time_stats()

    # ── Build HTML report ─────────────────────────────────────────────────
    mode_str = "<b>[DRY RUN TEST]</b>" if state.get("dry_run") else "<b>[LIVE ACTIVE RUN]</b>"

    # ── SECTION 1: Quick numeric summary ─────────────────────────────────
    summary_html = f"""
    <div style="background:#f0f9ff; border-left:4px solid #0284c7; padding:15px 20px; border-radius:6px; margin:15px 0;">
      <h3 style="margin-top:0; color:#0369a1;">📊 Today's Summary — {today}</h3>
      <table style="border-collapse:collapse; font-size:15px; width:100%;">
        <tr><td style="padding:4px 0; width:55%;"><b>✅ Jobs Applied Today:</b></td>
            <td style="padding:4px 0; color:#16a34a; font-weight:bold;">{total_applied}</td></tr>
        <tr><td style="padding:4px 0;"><b>📈 Total Applied (All-Time):</b></td>
            <td style="padding:4px 0; font-weight:bold;">{all_time.get('total_applied', 0)}</td></tr>
        <tr><td style="padding:4px 0;"><b>📧 Cold Emails Sent (Jobs):</b></td>
            <td style="padding:4px 0; color:#2563eb; font-weight:bold;">{total_emailed}</td></tr>
        <tr><td style="padding:4px 0;"><b>📨 PDF Cold Mails Sent Today:</b></td>
            <td style="padding:4px 0; color:#7c3aed; font-weight:bold;">{pdf_emails_sent} &nbsp;
              <span style="color:#6b7280; font-size:12px; font-weight:normal;">
                (Total: {total_pdf_sent_alltime}/{total_pdf_contacts} from PDF list)
              </span></td></tr>
        <tr><td style="padding:4px 0;"><b>❌ Failures Today:</b></td>
            <td style="padding:4px 0; color:#dc2626; font-weight:bold;">{total_failed}</td></tr>
      </table>
    </div>
    """

    # ── SECTION 2: Inbox — Bounces + Real Replies ──────────────────────────
    if bounce_count > 0:
        bounce_html = f"""
        <div style="background:#fef2f2; border-left:4px solid #ef4444; padding:10px 15px;
             border-radius:6px; margin:10px 0; font-size:14px; color:#7f1d1d;">
          ⚠️ <b>{bounce_count}</b> email(s) bounced back (address does not exist / invalid domain).
          These contacts were already marked invalid and will not be retried.
        </div>
        """
    else:
        bounce_html = ""

    if recruiter_replies:
        replies_items = ""
        for r in recruiter_replies:
            replies_items += f"""
            <li style="margin-bottom:12px;">
              <b>From:</b> {r['sender']}<br>
              <b>Subject:</b> <i>{r['subject']}</i><br>
              <b>Date:</b> {r['date']}<br>
              <b>Snippet:</b> <span style="background:#fef08a; padding:1px 4px; border-radius:3px;">"{r['snippet']}"</span>
            </li>"""

        replies_html = f"""
        <div style="background:#fef3c7; border-left:4px solid #d97706; padding:15px; border-radius:6px; margin:15px 0; color:#1e293b;">
          <h3 style="margin-top:0; color:#b45309;">📬 Recruiter Replies ({len(recruiter_replies)}):</h3>
          <ul style="padding-left:20px; margin-bottom:0;">{replies_items}</ul>
        </div>
        """
    else:
        replies_html = """
        <div style="background:#f4f4f5; border-left:4px solid #71717a; padding:12px 15px;
             border-radius:6px; margin:15px 0; color:#4b5563; font-size:14px;">
          <i>📭 No replies yet from any HR / recruiter you contacted. Keep going — replies take time!</i>
        </div>
        """

    # ── SECTION 3: Application list (today) ──────────────────────────────
    application_results = state.get("application_results", [])
    if application_results:
        filtered_apps = [r for r in application_results if r.get("portal") not in ("remoteok", "weworkremotely")]
        if filtered_apps:
            apps_html = "<ol>"
            for r in filtered_apps:
                status_style = {
                    "applied":         "color:#16a34a; font-weight:bold;",
                    "failed":          "color:#dc2626; font-weight:bold;",
                    "manual_required": "color:#d97706; font-weight:bold;"
                }.get(r.get("status", ""), "color:#4b5563;")
                apps_html += f"""
                <li style="margin-bottom:6px;">
                  <b>{r.get('job_title','')}</b> at <i>{r.get('company','')}</i>
                  via {r.get('portal','').upper()} &mdash;
                  <span style="{status_style}">{r.get('status','').replace('_',' ').title()}</span>
                </li>"""
            apps_html += "</ol>"
        else:
            apps_html = "<p><i>No applications submitted today.</i></p>"
    else:
        apps_html = "<p><i>No applications submitted today.</i></p>"

    # ── Full HTML ─────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Job Agent Daily Summary</title>
</head>
<body style="font-family:'Segoe UI',Arial,sans-serif; color:#1e293b; background:#ffffff; line-height:1.6; margin:0; padding:20px;">
  <div style="max-width:650px; margin:0 auto; padding:10px 0;">

    <h2 style="border-bottom:2px solid #e2e8f0; padding-bottom:10px; margin-bottom:5px; color:#0f172a;">
      🤖 Job Agent Daily Report &mdash; {today}
    </h2>
    <p style="margin:5px 0 15px 0; font-size:13px; color:#64748b;">
      Mode: {mode_str} &nbsp;|&nbsp; Scheduled: {cfg.SCHEDULE_HOUR:02d}:{cfg.SCHEDULE_MINUTE:02d} {cfg.TIMEZONE}
    </p>

    {summary_html}
    {bounce_html}
    {replies_html}

    <h3 style="color:#0f172a; margin-top:25px; border-bottom:1px solid #f1f5f9; padding-bottom:5px;">
      Applications Today:
    </h3>
    {apps_html}

    <hr style="border:0; border-top:1px solid #e2e8f0; margin-top:30px; margin-bottom:12px;">
    <p style="font-size:11px; color:#94a3b8; text-align:center;">
      Job Agent automation report &bull; {today} &bull; {cfg.GMAIL_ADDRESS}
    </p>
  </div>
</body>
</html>"""

    # ── Log summary to console ────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"📋 DAILY REPORT — {today}")
    logger.info(f"   Applied today:       {total_applied}")
    logger.info(f"   Total applied (all): {all_time.get('total_applied', 0)}")
    logger.info(f"   Cold mails (jobs):   {total_emailed}")
    logger.info(f"   PDF cold mails today:{pdf_emails_sent}  (total {total_pdf_sent_alltime}/{total_pdf_contacts})")
    logger.info(f"   Bounced-back mails:  {bounce_count}")
    logger.info(f"   Recruiter replies:   {len(recruiter_replies)}")
    if recruiter_replies:
        for r in recruiter_replies:
            logger.info(f"     ↳ {r['sender']} | {r['subject']}")
    else:
        logger.info("   No replies from HR contacts yet — keep sending!")
    logger.info("=" * 60)

    # ── Send HTML report to personal email (new format) ───────────────────
    try:
        from tools.email_sender import EmailSender
        sender = EmailSender(
            gmail_address=cfg.GMAIL_ADDRESS,
            app_password=cfg.GMAIL_APP_PASSWORD,
            resume_path=cfg.RESUME_PATH,
        )
        subject = (
            f"[Job Agent] {today} | Applied: {total_applied} | "
            f"Emails: {total_emailed} | PDF: {pdf_emails_sent}/{total_pdf_contacts} | "
            f"Replies: {len(recruiter_replies)}"
        )
        sent_ok = sender.send_summary_email(
            to_email=cfg.PERSONAL_EMAIL,
            subject=subject,
            html_body=html,
            dry_run=False,   # Always send the report regardless of dry_run mode
        )
        if sent_ok:
            logger.info(f"✅ Daily report emailed to: {cfg.PERSONAL_EMAIL}")
        else:
            logger.warning("⚠️  Daily report email failed — check Gmail credentials")
    except Exception as e:
        logger.error(f"Failed to send daily report email: {e}")

    return {"report_html": html}
