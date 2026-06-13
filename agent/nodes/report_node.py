"""
agent/nodes/report_node.py — Generate and send daily summary report
Sends a beautiful HTML email summary to your own email at end of day run.
"""
import logging
import logging
from datetime import datetime
from typing import Dict
from agent.state import AgentState
from database.db_manager import DatabaseManager
from tools.email_sender import EmailSender
from tools.inbox_monitor import fetch_hr_replies
import config as cfg

logger = logging.getLogger(__name__)


def generate_report_node(state: AgentState) -> Dict:
    """
    LangGraph node: Generate daily report and email it to yourself.
    Formats the report as a concise, clean decorated text summary (HTML formatted).
    Includes:
    - Gold-highlighted career inbox HR replies (text highlight)
    - Today's stats & all-time totals
    - Chronological list of companies applied/emailed
    """
    db = DatabaseManager(cfg.DB_PATH)
    today = state.get("run_date", datetime.now().strftime("%Y-%m-%d"))

    # ── Fetch career inbox replies (IMAP monitor) ────────────────────
    hr_replies = fetch_hr_replies(days_back=3)

    # ── Today's stats ─────────────────────────────────────────────────
    total_scraped = state.get("total_scraped", 0)
    total_new = state.get("total_new", 0)
    total_applied = state.get("total_applied", 0)
    total_emailed = state.get("total_emailed", 0)
    total_failed = state.get("total_failed", 0)
    pdf_emails_sent = state.get("pdf_emails_sent", 0)

    # ── PDF HR outreach stats ───────────────────────────────────────────
    pdf_stats = {"total": 0, "sent": 0, "sent_today": 0}
    try:
        pdf_stats = db.get_pdf_hr_stats()
    except Exception:
        pass

    # ── All-time stats ────────────────────────────────────────────────
    all_time = db.get_all_time_stats()

    # ── Companies today ───────────────────────────────────────────────
    application_results = state.get("application_results", [])
    emails_sent = state.get("emails_sent", [])

    # ── Build Decorated Text-Like HTML report ─────────────────────────
    # We send HTML but format it to look like clean, decorated plain-text with standard fonts, bold/italic.
    mode_str = "<b>[DRY RUN TEST]</b>" if state.get("dry_run") else "<b>[LIVE ACTIVE RUN]</b>"

    # Format HR replies list
    replies_html = ""
    if hr_replies:
        replies_html = """
        <div style="background:#fef3c7; border-left:4px solid #d97706; padding:15px; border-radius:6px; margin:20px 0; color:#1e293b;">
            <h3 style="margin-top:0; color:#b45309;">📬 IMPORTANT REPLIES IN YOUR CAREER INBOX:</h3>
            <ul style="padding-left:20px; margin-bottom:0;">
        """
        for r in hr_replies:
            replies_html += f"""
                <li style="margin-bottom:12px;">
                    <b>From:</b> {r['sender']}<br>
                    <b>Subject:</b> <i>{r['subject']}</i><br>
                    <b>Date:</b> {r['date']}<br>
                    <b>Snippet:</b> <span style="background:#fef08a; padding:1px 4px; border-radius:3px;">"{r['snippet']}"</span>
                </li>
            """
        replies_html += "</ul></div>"
    else:
        replies_html = """
        <div style="background:#f4f4f5; border-left:4px solid #71717a; padding:15px; border-radius:6px; margin:20px 0; color:#4b5563;">
            <i>No new HR or company email replies were detected in your careers inbox over the last 3 days.</i>
        </div>
        """

    # Format applications today list
    apps_text_list = ""
    if application_results:
        filtered_apps = [r for r in application_results if r.get("portal") not in ("remoteok", "weworkremotely")]
        if filtered_apps:
            apps_text_list = "<ol>"
            for r in filtered_apps:
                status_style = {
                    "applied": "color:#16a34a; font-weight:bold;",
                    "failed": "color:#dc2626; font-weight:bold;",
                    "manual_required": "color:#d97706; font-weight:bold;"
                }.get(r.get("status", ""), "color:#4b5563;")
                
                apps_text_list += f"""
                <li style="margin-bottom:6px;">
                    <b>{r.get('job_title','')}</b> at <i>{r.get('company','')}</i> via {r.get('portal','').upper()} &mdash; Status: <span style="{status_style}">{r.get('status','').replace('_',' ').title()}</span>
                </li>"""
            apps_text_list += "</ol>"
        else:
            apps_text_list = "<p><i>No job applications were submitted today.</i></p>"
    else:
        apps_text_list = "<p><i>No job applications were submitted today.</i></p>"

    # Format emails sent today list
    emails_text_list = ""
    if emails_sent:
        emails_text_list = "<ul>"
        for e in emails_sent:
            emails_text_list += f"""
            <li style="margin-bottom:6px;">
                Emailed <b>{e.get('company','')}</b> (<i>{e.get('job_title','')}</i>) &rarr; Recipient: <u>{e.get('to_email','')}</u>
            </li>"""
        emails_text_list += "</ul>"
    else:
        emails_text_list = "<p><i>No cold outreach emails were sent today.</i></p>"

    # HTML Body: concise, clean decorated text style
    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Job Agent Daily Summary</title>
</head>
<body style="font-family:'Segoe UI',Arial,sans-serif; color:#1e293b; background:#ffffff; line-height:1.6; margin:0; padding:20px;">
  <div style="max-width:650px; margin:0 auto; padding:10px 0;">
    
    <h2 style="border-bottom:2px solid #e2e8f0; padding-bottom:10px; margin-bottom:10px; color:#0f172a;">
      🤖 Job Agent Summary Report &mdash; {today}
    </h2>
    <p style="margin:5px 0 20px 0; font-size:14px; color:#64748b;">
      Run Mode: {mode_str} &nbsp;|&nbsp; Current Date: <b>{today}</b>
    </p>

    <!-- INBOX REPLIES ALERT SECTION -->
    {replies_html}

    <!-- STATS SUMMARY -->
    <h3 style="color:#0f172a; margin-top:25px; border-bottom:1px solid #f1f5f9; padding-bottom:5px;">📊 Daily Run Statistics:</h3>
    <ul style="padding-left:20px;">
      <li><b>Jobs Scraped:</b> {total_scraped}</li>
      <li><b>New Jobs Discovered:</b> {total_new}</li>
      <li><b>Successfully Applied:</b> <span style="color:#16a34a; font-weight:bold;">{total_applied}</span></li>
      <li><b>Cold Emails Sent (jobs):</b> <span style="color:#2563eb; font-weight:bold;">{total_emailed}</span></li>
      <li><b>PDF HR Drip Emails Sent:</b> <span style="color:#7c3aed; font-weight:bold;">{pdf_emails_sent}</span> <span style="color:#6b7280; font-size:12px;">(Total: {pdf_stats.get('sent', 0)}/{pdf_stats.get('total', '?')} from PDF list)</span></li>
      <li><b>Failures:</b> <span style="color:#dc2626; font-weight:bold;">{total_failed}</span></li>
    </ul>

    <h3 style="color:#0f172a; margin-top:25px; border-bottom:1px solid #f1f5f9; padding-bottom:5px;">📈 All-Time Cumulative Stats:</h3>
    <ul style="padding-left:20px;">
      <li><b>Total Applied (All-Time):</b> <b>{all_time.get('total_applied', 0)}</b></li>
      <li><b>Total Cold Emails Sent:</b> <b>{all_time.get('total_emailed', 0)}</b></li>
      <li><b>Unique Companies Contacted:</b> <b>{all_time.get('unique_companies', 0)}</b></li>
    </ul>

    <!-- DETAILS OF TODAY'S APPLICATIONS -->
    <h3 style="color:#0f172a; margin-top:25px; border-bottom:1px solid #f1f5f9; padding-bottom:5px;">Applications Today:</h3>
    {apps_text_list}

    <!-- DETAILS OF TODAY'S COLD OUTREACH (jobs) -->
    <h3 style="color:#0f172a; margin-top:25px; border-bottom:1px solid #f1f5f9; padding-bottom:5px;">Cold Outreach (Job-Based) Today:</h3>
    {emails_text_list}

    <!-- PDF HR DRIP CAMPAIGN SECTION -->
    <div style="background:#f5f3ff; border-left:4px solid #7c3aed; padding:15px; border-radius:6px; margin:20px 0; color:#1e293b;">
      <h3 style="margin-top:0; color:#6d28d9;">PDF HR Drip Campaign Progress:</h3>
      <ul style="padding-left:20px; margin-bottom:0;">
        <li><b>Sent today:</b> <span style="color:#7c3aed; font-weight:bold;">{pdf_emails_sent}</span> emails</li>
        <li><b>All-time sent:</b> {pdf_stats.get('sent', 0)} out of {pdf_stats.get('total', '?')} PDF contacts</li>
        <li><b>Remaining in list:</b> {max(0, (pdf_stats.get('total', 0) or 0) - (pdf_stats.get('sent', 0) or 0))} contacts</li>
        <li><b>At 50/day, list completes in:</b> ~{max(0, ((pdf_stats.get('total', 0) or 0) - (pdf_stats.get('sent', 0) or 0)) // 50 + 1)} more days</li>
      </ul>
    </div>

    <hr style="border:0; border-top:1px solid #e2e8f0; margin-top:35px; margin-bottom:15px;">
    <p style="font-size:12px; color:#94a3b8; text-align:center;">
      Daily job agent automation report &bull; Triggered daily at {cfg.SCHEDULE_HOUR:02d}:{cfg.SCHEDULE_MINUTE:02d} {cfg.TIMEZONE} &bull; Personal Inbox: {cfg.PERSONAL_EMAIL}
    </p>

  </div>
</body>
</html>
"""

    # Send report to your personal inbox — ALWAYS send even in dry_run mode
    # (You need to see the daily summary regardless of whether jobs were applied or not)
    try:
        sender = EmailSender(
            gmail_address=cfg.GMAIL_ADDRESS,
            app_password=cfg.GMAIL_APP_PASSWORD,
            resume_path=cfg.RESUME_PATH,
        )

        subject = (
            f"[Job Agent] {today} | Applied:{total_applied} | "
            f"Emailed:{total_emailed} | PDF:{pdf_emails_sent}"
        )
        sent_ok = sender.send_summary_email(
            to_email=cfg.PERSONAL_EMAIL,
            subject=subject,
            html_body=html,
            dry_run=False,   # ALWAYS send the summary report — never skip it
        )
        if sent_ok:
            logger.info(f"Daily report sent to personal email: {cfg.PERSONAL_EMAIL}")
        else:
            logger.warning("Daily report email failed to send — check Gmail credentials")
    except Exception as e:
        logger.error(f"Failed to send daily report email: {e}")

    return {"report_html": html}
