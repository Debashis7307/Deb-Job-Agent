"""
tools/inbox_monitor.py — Connects to career inbox via IMAP to look up replies from HR/companies.
"""
import imaplib
import email
from email.header import decode_header
import datetime
import logging
import re
import config as cfg

logger = logging.getLogger(__name__)


def fetch_hr_replies(days_back: int = 3) -> list:
    """
    Connect to Gmail via IMAP and fetch important emails/replies from HR/companies.
    Returns a list of dicts: {"sender": str, "subject": str, "date": str, "snippet": str}
    """
    replies = []
    try:
        # Connect to Gmail IMAP
        logger.info(f"Connecting to IMAP inbox at imap.gmail.com for {cfg.GMAIL_ADDRESS}...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(cfg.GMAIL_ADDRESS, cfg.GMAIL_APP_PASSWORD)
        mail.select("inbox")

        # Calculate date for search (e.g. SINCE "01-Jun-2026")
        since_date = (datetime.datetime.now() - datetime.timedelta(days=days_back)).strftime("%d-%b-%Y")
        status, data = mail.search(None, f'SINCE {since_date}')

        if status != "OK":
            logger.warning("IMAP search failed or returned status error")
            return []

        email_ids = data[0].split()
        if not email_ids:
            logger.info("No new career inbox emails found in the last few days")
            return []

        # List of domains to exclude (job portals, newsletters, system notifications)
        exclude_domains = {
            "linkedin.com", "naukri.com", "internshala.com", "wellfound.com", 
            "google.com", "github.com", "vercel.com", "youtube.com", "facebook.com",
            "twitter.com", "instagram.com", "bounce", "newsletter", "noreply", 
            "no-reply", "alert", "notification", "digest", "update", "verify",
            "security", "promo", "billing", "subscriptions"
        }

        logger.info(f"IMAP: Found {len(email_ids)} recent emails in inbox. Checking for important replies...")

        # Read in reverse order (most recent first), limit to last 30 emails to be fast
        for mail_id in reversed(email_ids[-30:]):
            status, msg_data = mail.fetch(mail_id, "(RFC822)")
            if status != "OK":
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            # Get Subject
            subject, encoding = decode_header(msg.get("Subject", "No Subject"))[0]
            if isinstance(subject, bytes):
                subject = subject.decode(encoding or "utf-8", errors="ignore")

            # Get Sender
            from_header = msg.get("From", "")
            sender_name, sender_email = "", ""
            match = re.search(r'(.*?)<(.*?)>', from_header)
            if match:
                sender_name = match.group(1).strip('" \t')
                sender_email = match.group(2).strip().lower()
            else:
                sender_email = from_header.strip().lower()
                sender_name = sender_email

            # Exclude self
            if cfg.GMAIL_ADDRESS.lower() in sender_email:
                continue

            # Exclude standard portals, notifications, and newsletter domains
            if any(domain in sender_email for domain in exclude_domains):
                continue

            # Parse date
            date_str = msg.get("Date", "")

            # Get Snippet / Body snippet
            snippet = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))
                    if content_type == "text/plain" and "attachment" not in content_disposition:
                        payload = part.get_payload(decode=True)
                        if payload:
                            snippet = payload.decode(errors="ignore")[:300].strip()
                            break
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    snippet = payload.decode(errors="ignore")[:300].strip()

            # Clean up body snippet whitespace/newlines
            snippet = re.sub(r'\s+', ' ', snippet)
            if len(snippet) > 150:
                snippet = snippet[:150] + "..."

            replies.append({
                "sender": from_header,
                "sender_email": sender_email,
                "subject": subject,
                "date": date_str,
                "snippet": snippet or "[No text content]"
            })

        mail.close()
        mail.logout()
        logger.info(f"IMAP monitor: Successfully fetched {len(replies)} relevant replies")

    except Exception as e:
        logger.error(f"Error fetching emails from inbox: {e}")

    return replies
