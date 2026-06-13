"""
tools/email_sender.py — Gmail SMTP email sender with PDF resume attachment
"""
import smtplib
import logging
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class EmailSender:
    """Handles sending cold emails via Gmail SMTP."""

    def __init__(self, gmail_address: str, app_password: str, resume_path: str):
        self.gmail_address = gmail_address
        self.app_password = app_password
        self.resume_path = Path(resume_path)
        self._validate_setup()

    def _validate_setup(self):
        """Validate credentials and resume file."""
        if not self.gmail_address or not self.app_password:
            raise ValueError("Gmail address and app password required")
        if not self.resume_path.exists():
            logger.warning(f"Resume not found at {self.resume_path}. Emails will be sent without attachment.")

    def send_cold_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        dry_run: bool = True,
        cc: Optional[str] = None
    ) -> bool:
        """
        Send a cold email with resume attached.
        
        Args:
            to_email: Recipient HR email
            subject: Email subject line
            body: Email body (plain text)
            dry_run: If True, just logs the email without sending
            cc: Optional CC address
            
        Returns:
            True if sent successfully, False otherwise
        """
        if dry_run:
            logger.info(f"[DRY RUN] Would send email to: {to_email}")
            logger.info(f"[DRY RUN] Subject: {subject}")
            logger.info(f"[DRY RUN] Body preview: {body[:200]}...")
            return True

        try:
            msg = MIMEMultipart()
            msg["From"] = self.gmail_address
            msg["To"] = to_email
            msg["Subject"] = subject
            if cc:
                msg["Cc"] = cc

            # Add email body
            msg.attach(MIMEText(body, "plain"))

            # Attach resume if it exists
            if self.resume_path.exists():
                with open(self.resume_path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename={self.resume_path.name}"
                    )
                    msg.attach(part)

            # Send via Gmail SMTP
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self.gmail_address, self.app_password)
                recipients = [to_email]
                if cc:
                    recipients.append(cc)
                server.sendmail(self.gmail_address, recipients, msg.as_string())

            logger.info(f"✅ Email sent to {to_email}: {subject}")
            return True

        except smtplib.SMTPAuthenticationError:
            logger.error("❌ Gmail authentication failed. Check your App Password in .env")
            return False
        except smtplib.SMTPRecipientsRefused:
            logger.warning(f"Email rejected by server for: {to_email}")
            return False
        except Exception as e:
            logger.error(f"Email send failed to {to_email}: {e}")
            return False

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

        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.gmail_address
            msg["To"] = to_email
            msg["Subject"] = subject

            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self.gmail_address, self.app_password)
                server.sendmail(self.gmail_address, to_email, msg.as_string())

            logger.info(f"✅ Summary email sent to {to_email}")
            return True

        except Exception as e:
            logger.error(f"Summary email failed: {e}")
            return False

    def batch_send(
        self,
        emails: list,
        delay_between: float = 30.0,
        dry_run: bool = True
    ) -> dict:
        """
        Send a batch of emails with delay between each.
        
        emails: list of dicts with keys: to_email, subject, body
        delay_between: seconds to wait between emails (default 30s to avoid spam)
        """
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

                # Wait between emails (except after last one)
                if i < len(emails) - 1:
                    logger.info(f"Waiting {delay_between}s before next email...")
                    time.sleep(delay_between)

            except Exception as e:
                logger.error(f"Batch send error: {e}")
                results["failed"] += 1

        logger.info(f"Batch complete: {results}")
        return results
