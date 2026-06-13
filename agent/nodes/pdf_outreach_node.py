"""
agent/nodes/pdf_outreach_node.py — Daily 50-email drip from PDF HR contacts

This node runs AFTER the main email_node each day.
It picks the next 50 unsent HR contacts from the PDF list,
generates personalized cold emails via Gemini, and sends them.
"""
import logging
import json
import time
from typing import Dict, List
from agent.state import AgentState
import config as cfg

logger = logging.getLogger(__name__)

# Max emails to send per run from PDF (50/day as requested)
PDF_BATCH_SIZE = 50
# Delay between emails (seconds) — don't spam SMTP
EMAIL_DELAY_SECONDS = 20


def _validate_email_mx(email: str) -> bool:
    """
    Quick MX record validation — checks that the email's domain
    has at least one MX record configured (can receive email).
    Returns True if domain looks valid, False if no MX found.
    Falls back to True if dnspython is unavailable (don't block on missing dep).
    """
    import socket
    try:
        domain = email.split("@")[-1].lower().strip()
        if not domain or "." not in domain:
            return False

        # Fast: DNS host resolution check first
        try:
            socket.gethostbyname(domain)
        except socket.gaierror:
            return False  # Domain doesn't resolve at all — definitely invalid

        # MX record check via dnspython (installed in venv)
        try:
            import dns.resolver
            resolver = dns.resolver.Resolver()
            resolver.timeout = 3.0
            resolver.lifetime = 3.0
            answers = resolver.resolve(domain, "MX")
            return len(answers) > 0
        except Exception:
            # If MX lookup fails but host resolves, trust the host resolution
            return True
    except Exception:
        return True  # On unexpected error, don't block — let email attempt proceed


def pdf_outreach_node(state: AgentState) -> Dict:
    """
    LangGraph node: Send daily batch of 50 personalized cold emails
    to HR contacts from the PDF list.

    - Calls pdf_hr_parser.get_next_pdf_hr_batch(50)
    - Validates emails via MX check (skips invalid ones — prevents bounces)
    - Generates personalized emails via Gemini (batched 5 at a time)
    - Sends each via EmailSender
    - Marks each as sent/invalid in pdf_hr_outreach table
    """
    from tools.pdf_hr_parser import get_next_pdf_hr_batch, mark_pdf_hr_sent, get_pdf_hr_stats
    from tools.email_sender import EmailSender

    dry_run = state.get("dry_run", True)
    run_date = state.get("run_date", "")

    # ── Check how many already sent today from PDF list ───────────────────
    stats = get_pdf_hr_stats()
    already_sent_today = int(stats.get("sent_today") or 0)  # Guard against None from SQLite
    remaining_quota = max(0, PDF_BATCH_SIZE - already_sent_today)

    if remaining_quota == 0:
        logger.info(f"PDF outreach quota reached for today ({PDF_BATCH_SIZE}/day). Skipping.")
        return {"pdf_emails_sent": 0}

    # Fetch more contacts than needed to account for invalid ones that get filtered out
    fetch_count = min(remaining_quota * 2, remaining_quota + 30)
    contacts = get_next_pdf_hr_batch(count=fetch_count)
    if not contacts:
        logger.info(f"PDF HR: No more unsent contacts. All {stats.get('total_sent', 0)} contacts emailed!")
        return {"pdf_emails_sent": 0}

    # ── Pre-validate emails via MX check (skip bad domains) ────────────────
    valid_contacts = []
    skipped_invalid = 0
    for contact in contacts:
        email = contact.get("email", "")
        if not email or "@" not in email:
            skipped_invalid += 1
            continue
        if _validate_email_mx(email):
            valid_contacts.append(contact)
            if len(valid_contacts) >= remaining_quota:
                break  # We have enough valid ones
        else:
            logger.debug(f"Skipping invalid email (no MX): {email}")
            mark_pdf_hr_sent(
                email=email,
                name=contact.get("name", ""),
                company=contact.get("company", ""),
                designation=contact.get("designation", ""),
                status="invalid",  # Mark as invalid so we don't try again
            )
            skipped_invalid += 1

    if skipped_invalid > 0:
        logger.info(f"PDF HR: Skipped {skipped_invalid} contacts with invalid/unresolvable email domains")

    if not valid_contacts:
        logger.warning("PDF HR: No valid emails found in this batch. All had bad domains.")
        return {"pdf_emails_sent": 0}

    logger.info(
        f"PDF HR Outreach: Sending {len(valid_contacts)} emails "
        f"(total sent so far: {stats.get('total_sent', 0)}/{stats.get('total_in_pdf', '?')})"
    )

    # ── Generate personalized emails in batches of 5 ──────────────────────
    email_payloads = _generate_pdf_emails_batch(valid_contacts)

    # ── Send emails ───────────────────────────────────────────────────────
    sender = EmailSender(
        gmail_address=cfg.GMAIL_ADDRESS,
        app_password=cfg.GMAIL_APP_PASSWORD,
        resume_path=cfg.RESUME_PDF_PATH,
    )

    sent_count = 0
    failed_count = 0

    for i, payload in enumerate(email_payloads):
        contact = valid_contacts[i] if i < len(valid_contacts) else {}
        email_addr = contact.get("email", payload.get("to_email", ""))

        if not email_addr or "@" not in email_addr:
            logger.warning(f"Skipping invalid email: {email_addr}")
            continue

        success = sender.send_cold_email(
            to_email=email_addr,
            subject=payload.get("subject", "Exciting opportunity to connect"),
            body=payload.get("body", ""),
            dry_run=dry_run,
        )

        if success:
            sent_count += 1
            # Only mark as 'sent' in DB for REAL sends — dry_run must not block future real runs
            db_status = "sent" if not dry_run else "dry_run"
            mark_pdf_hr_sent(
                email=email_addr,
                name=contact.get("name", ""),
                company=contact.get("company", ""),
                designation=contact.get("designation", ""),
                status=db_status,
            )
            logger.info(
                f"[{sent_count}/{len(valid_contacts)}] PDF HR sent to {email_addr} "
                f"({contact.get('name', '?')} @ {contact.get('company', '?')})"
            )
        else:
            failed_count += 1
            mark_pdf_hr_sent(
                email=email_addr,
                name=contact.get("name", ""),
                company=contact.get("company", ""),
                designation=contact.get("designation", ""),
                status="failed",
            )

        # Delay between sends (avoid SMTP limits)
        if i < len(email_payloads) - 1 and not dry_run:
            time.sleep(EMAIL_DELAY_SECONDS)

    logger.info(
        f"PDF HR Outreach complete: {sent_count} sent, {failed_count} failed, {skipped_invalid} invalid "
        f"({'DRY RUN' if dry_run else 'LIVE'})"
    )

    return {"pdf_emails_sent": sent_count}


def _generate_pdf_emails_batch(contacts: List[Dict]) -> List[Dict]:
    """
    Generate personalized cold emails for each contact using Gemini.
    Batches 5 contacts per LLM call to stay under rate limits.
    Returns list of {to_email, subject, body} dicts.

    Retry strategy:
    - 503 UNAVAILABLE  → transient overload; retry with exponential back-off
    - 429 RESOURCE_EXHAUSTED → quota; longer back-off before retry
    - Up to 4 attempts per batch before falling back to template
    """
    from google import genai
    from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
    from tenacity import (
        retry,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
        before_sleep_log,
    )
    import config as cfg

    client = genai.Client(api_key=cfg.GEMINI_API_KEY)
    results = []

    # Load user profile for personalization
    import json
    from pathlib import Path
    profile_path = Path(cfg.USER_PROFILE_PATH) if hasattr(cfg, "USER_PROFILE_PATH") else Path("data/user_profile.json")
    user_name = "Debashis Bera"
    user_skills = "Python, C++, AI/ML, Generative AI, Agentic AI, LangGraph"
    user_bg = "Final year B.Tech CSE student"

    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text())
            user_name = profile.get("name", user_name)
            skills = profile.get("skills", {})
            user_skills = ", ".join(
                skills.get("languages", []) + skills.get("ai_ml", [])
            ) or user_skills
            user_bg = profile.get("background", user_bg)
        except Exception:
            pass

    # ── Gemini call with retry (503 / 429 safe) ────────────────────────────
    @retry(
        retry=retry_if_exception_type((ResourceExhausted, ServiceUnavailable, Exception)),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        stop=stop_after_attempt(4),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _call_gemini_with_retry(prompt_text: str) -> str:
        """Call Gemini with automatic retry on 503/429."""
        resp = client.models.generate_content(
            model=cfg.GEMINI_MODEL,
            contents=prompt_text,
        )
        return resp.text

    BATCH_SIZE = 5
    for batch_start in range(0, len(contacts), BATCH_SIZE):
        batch = contacts[batch_start: batch_start + BATCH_SIZE]

        # Build batch prompt
        contacts_json = json.dumps([
            {
                "id": i,
                "to_name": c.get("name", "Hiring Manager"),
                "to_designation": c.get("designation", "HR"),
                "company": c.get("company", "your company"),
                "email": c.get("email", ""),
            }
            for i, c in enumerate(batch)
        ], indent=2)

        prompt = f"""You are {user_name}, a {user_bg} skilled in {user_skills}.
Write personalized cold emails to these HR/Hiring managers for job opportunities.

Rules:
- Each email must be unique and personalized using the person's name, designation, and company
- Subject line: short, compelling, professional (max 10 words)
- Body: 3-4 short paragraphs — greeting, brief intro, why them, call-to-action
- Tone: professional yet warm, confident but humble (student seeking opportunity)
- Mention resume is attached
- Max 200 words per email
- End with: "Best regards,\\n{user_name}"

Contacts:
{contacts_json}

Return ONLY valid JSON array:
[
  {{
    "id": 0,
    "to_email": "email from contacts",
    "subject": "...",
    "body": "..."
  }},
  ...
]
No markdown, no explanation, just JSON."""

        try:
            text = _call_gemini_with_retry(prompt)
            text = text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]

            batch_results = json.loads(text)

            for item in batch_results:
                idx = item.get("id", 0)
                if idx < len(batch):
                    results.append({
                        "to_email": batch[idx].get("email", item.get("to_email", "")),
                        "subject": item.get("subject", "Opportunity to connect — Fresher CSE"),
                        "body": item.get("body", ""),
                    })

            logger.info(f"Generated {len(batch_results)} PDF emails (batch {batch_start//BATCH_SIZE + 1})")

        except json.JSONDecodeError as e:
            logger.warning(f"Gemini JSON parse error for PDF email batch: {e}. Using fallback.")
            for c in batch:
                results.append(_fallback_email(c, user_name, user_skills))

        except Exception as e:
            logger.error(f"Gemini call failed for PDF email batch after retries: {e}. Using fallback.")
            for c in batch:
                results.append(_fallback_email(c, user_name, user_skills))

        # Rate limit buffer — 4s to reduce 429 pressure
        time.sleep(4)

    return results


def _fallback_email(contact: Dict, user_name: str, user_skills: str) -> Dict:
    """Fallback email template if Gemini fails."""
    name = contact.get("name", "Hiring Manager")
    designation = contact.get("designation", "HR").strip()
    email = contact.get("email", "")

    # Robustly determine company name — PDF parser sometimes stores
    # a job title in the company field. If it looks like a title, derive from domain.
    HR_TITLE_KEYWORDS = [
        "director", "manager", "recruiter", "vice president", "vp ", "head of",
        "chief", " officer", " hr ", "talent", "associate", "avp", "svp"
    ]
    raw_company = contact.get("company", "").strip()
    if not raw_company or any(kw in raw_company.lower() for kw in HR_TITLE_KEYWORDS):
        domain = email.split("@")[-1] if "@" in email else ""
        company = domain.split(".")[0].capitalize() if domain else "your company"
    else:
        company = raw_company

    greeting = f"Hi {name}," if name and name.lower() not in ["", "unknown", "n/a"] else "Hi there,"

    desig_context = (
        f"As {designation} at {company}, you would know best whether there are "
        f"relevant openings for a passionate fresher."
        if designation and designation.lower() not in ["hr", ""]
        else f"I believe you'd be the right person to connect with at {company}."
    )

    body = f"""{greeting}

I'm Debashis Bera, a final year B.Tech CSE student specializing in Python, AI/ML, and Generative AI. I'm reaching out to explore potential opportunities at {company}.

I've built production-grade autonomous AI agents (LangGraph), worked on GenAI pipelines, and have strong foundations in Python, C++, and system design. I'm eager to join a team where I can contribute meaningfully from day one.

{desig_context} I've attached my resume — I'd love a quick chat if there's any opening or referral opportunity that fits.

Thank you for your time!

Best regards,
{user_name}"""

    return {
        "to_email": email,
        "subject": f"Final Year CSE Student | Python & AI/ML | Opportunity at {company}",
        "body": body,
    }
