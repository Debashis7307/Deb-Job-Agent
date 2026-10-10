"""
tools/email_sender.py — Email sender with multi-provider support

SMTP PROVIDER PRIORITY (tries each in order until one works):
1. Brevo (formerly Sendinblue) — smtp-relay.brevo.com:587
   - 300 free emails/day, works from GitHub Actions cloud IPs ✅
   - Set BREVO_SMTP_LOGIN + BREVO_SMTP_KEY in env/secrets
2. Gmail SMTP — smtp.gmail.com:587 (STARTTLS)
   - Fallback if Brevo not configured
   - May be blocked from GitHub Actions IPs ⚠️

WHY BREVO: Gmail blocks SMTP from GitHub Actions (Azure cloud) IPs.
Brevo/SendGrid/Mailgun work reliably from cloud servers.
"""
import smtplib
import logging
import time
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── SMTP Provider Configs ──────────────────────────────────────────────────
SMTP_PROVIDERS = [
    {
        "name": "Brevo",
        "host": "smtp-relay.brevo.com",
        "port": 587,
        "login_env": "BREVO_SMTP_LOGIN",    # your Brevo account email
        "password_env": "BREVO_SMTP_KEY",   # Brevo SMTP key (not account password)
        "use_starttls": True,
    },
    {
        "name": "Gmail",
        "host": "smtp.gmail.com",
        "port": 587,
        "login_env": "GMAIL_ADDRESS",
        "password_env": "GMAIL_APP_PASSWORD",
        "use_starttls": True,
    },
]


def _get_working_smtp_config() -> Optional[dict]:
    """Return the first SMTP provider that has credentials configured."""
    for provider in SMTP_PROVIDERS:
        login = os.environ.get(provider["login_env"], "")
        password = os.environ.get(provider["password_env"], "")
        if login and password:
            logger.info(f"✅ Using SMTP provider: {provider['name']} ({provider['host']}:{provider['port']}) login={login}")
            return {**provider, "login": login, "password": password}
        else:
            logger.debug(f"⏭️  Skipping {provider['name']}: {provider['login_env']}={'set' if login else 'MISSING'}, {provider['password_env']}={'set' if password else 'MISSING'}")

    # Log ALL providers that were checked so the user knows what's missing
    logger.error(
        "❌ NO SMTP PROVIDER CONFIGURED! Checked:\n"
        "   1. Brevo: BREVO_SMTP_LOGIN + BREVO_SMTP_KEY  → both must be set\n"
        "   2. Gmail: GMAIL_ADDRESS + GMAIL_APP_PASSWORD → both must be set\n"
        "   Gmail SMTP is BLOCKED from cloud IPs (GitHub Actions). Use Brevo!\n"
        "   Sign up: https://app.brevo.com → Settings → SMTP & API"
    )
    return None


def _send_via_smtp(
    smtp_cfg: dict,
    msg: MIMEMultipart,
    from_addr: str,
    recipients: list,
    retries: int = 3,
) -> bool:
    """Send a composed message via the given SMTP config with retry."""
    last_err = None
    for attempt in range(retries):
        try:
            with smtplib.SMTP(smtp_cfg["host"], smtp_cfg["port"], timeout=30) as server:
                server.ehlo()
                if smtp_cfg.get("use_starttls", True):
                    server.starttls()
                    server.ehlo()
                server.login(smtp_cfg["login"], smtp_cfg["password"])
                server.sendmail(from_addr, recipients, msg.as_string())
            return True
        except smtplib.SMTPAuthenticationError as e:
            logger.error(
                f"❌ {smtp_cfg['name']} auth failed: {e}. "
                f"Check {smtp_cfg['login_env']} / {smtp_cfg['password_env']} env vars."
            )
            return False   # No point retrying auth failures
        except (smtplib.SMTPServerDisconnected, ConnectionResetError, OSError, TimeoutError) as e:
            last_err = e
            wait = 5 * (2 ** attempt)   # 5s, 10s, 20s
            logger.warning(f"{smtp_cfg['name']} connection dropped (attempt {attempt+1}/{retries}). Retry in {wait}s...")
            time.sleep(wait)
        except Exception as e:
            last_err = e
            logger.error(f"{smtp_cfg['name']} unexpected error: {e}")
            break

    logger.error(f"❌ {smtp_cfg['name']} failed after {retries} attempts: {last_err}")
    return False


class EmailSender:
    """Handles sending cold emails. Tries Brevo first, falls back to Gmail."""

    def __init__(self, gmail_address: str, app_password: str, resume_path: str):
        # Keep these for backward compatibility
        self.gmail_address = gmail_address
        self.app_password = app_password
        self.resume_path = Path(resume_path)
        self._validate_setup()

    def _validate_setup(self):
        """Validate credentials and resume file."""
        smtp_cfg = _get_working_smtp_config()
        if not smtp_cfg:
            logger.error("❌ No SMTP provider configured! Set BREVO_SMTP_LOGIN+BREVO_SMTP_KEY or GMAIL_ADDRESS+GMAIL_APP_PASSWORD")
        elif smtp_cfg["name"] == "Gmail":
            logger.warning(
                "⚠️  Using Gmail SMTP as fallback — this WILL FAIL from GitHub Actions cloud IPs!\n"
                "   Set BREVO_SMTP_LOGIN + BREVO_SMTP_KEY for reliable cloud email delivery."
            )
        else:
            logger.info(f"✅ Email sender ready: {smtp_cfg['name']} SMTP")
        if not self.resume_path.exists():
            logger.warning(f"Resume not found at {self.resume_path}. Emails will be sent without attachment.")

    def _build_message(
        self,
        from_addr: str,
        to_email: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        attach_resume: bool = True,
    ) -> MIMEMultipart:
        """Build the MIME message with optional resume attachment."""
        msg = MIMEMultipart()
        msg["From"] = from_addr
        msg["To"] = to_email
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        msg.attach(MIMEText(body, "plain"))

        if attach_resume and self.resume_path.exists():
            with open(self.resume_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename={self.resume_path.name}"
                )
                msg.attach(part)
        return msg

    def send_cold_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        dry_run: bool = True,
        cc: Optional[str] = None
    ) -> bool:
        """Send a cold email with resume attached."""
        if dry_run:
            logger.info(f"[DRY RUN] Would send email to: {to_email} | {subject}")
            return True

        smtp_cfg = _get_working_smtp_config()
        if not smtp_cfg:
            logger.error("❌ No SMTP provider available. Email not sent.")
            return False

        from_addr = smtp_cfg["login"]
        sender_name = os.environ.get("SENDER_DISPLAY_NAME", "Debashis Bera")
        reply_to = os.environ.get("GMAIL_ADDRESS", from_addr)
        # Use career Gmail in the From header so recruiters see "Debashis Bera <debashis.bera.careers@gmail.com>"
        from_header = f"{sender_name} <{reply_to}>"

        msg = self._build_message(from_header, to_email, subject, body, cc, attach_resume=True)
        msg["Reply-To"] = reply_to

        recipients = [to_email]
        if cc:
            recipients.append(cc)

        # Optional: BCC career email so a copy appears in career Gmail inbox
        bcc_career = os.environ.get("BCC_CAREER_EMAIL", "false").lower() == "true"
        if bcc_career and reply_to and reply_to not in recipients:
            recipients.append(reply_to)

        # SMTP envelope uses raw address (without display name)
        success = _send_via_smtp(smtp_cfg, msg, from_addr, recipients)
        if success:
            logger.info(f"✅ [{smtp_cfg['name']}] Email sent → {to_email}: {subject}")
        return success

    def send_summary_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        dry_run: bool = True
    ) -> bool:
        """Send the daily summary report email (HTML format, no attachment)."""
        if dry_run:
            logger.info(f"[DRY RUN] Would send summary to: {to_email}")
            return True

        smtp_cfg = _get_working_smtp_config()
        if not smtp_cfg:
            logger.error("❌ No SMTP provider available. Summary not sent.")
            return False

        from_addr = smtp_cfg["login"]
        msg = MIMEMultipart("alternative")
        msg["From"] = from_addr
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html"))

        success = _send_via_smtp(smtp_cfg, msg, from_addr, [to_email])
        if success:
            logger.info(f"✅ [{smtp_cfg['name']}] Summary email sent → {to_email}")
        return success

    def batch_send(
        self,
        emails: list,
        delay_between: float = 8.0,
        dry_run: bool = True
    ) -> dict:
        """Send a batch of emails with delay between each."""
        results = {"sent": 0, "failed": 0, "skipped": 0}

        for i, email_data in enumerate(emails):
            try:
                success = self.send_cold_email(
                    to_email=email_data["to_email"],
                    subject=email_data["subject"],
                    body=email_data["body"],
                    dry_run=dry_run
                )
                if success:
                    results["sent"] += 1
                else:
                    results["failed"] += 1

                if i < len(emails) - 1:
                    logger.info(f"Waiting {delay_between}s before next email...")
                    time.sleep(delay_between)

            except Exception as e:
                logger.error(f"Batch send error: {e}")
                results["failed"] += 1

        logger.info(f"Batch complete: {results}")
        return results
