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

# Max emails to send per run from PDF (reduced to 20/day to fit within GitHub Actions 90min timeout)
# 20 emails × 8s delay = ~3min sending, safe total runtime
PDF_BATCH_SIZE = 20
# Delay between emails (seconds) — enough to avoid SMTP rate limits, not too long
EMAIL_DELAY_SECONDS = 8


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

    Retry strategy (no google.api_core / tenacity needed):
    - Up to 4 attempts per batch with exponential back-off (5s, 10s, 20s, 40s)
    - Falls back to template email if all retries fail
    """
    from google import genai
    import json
    import config as cfg
    from pathlib import Path

    client = genai.Client(api_key=cfg.GEMINI_API_KEY)
    results = []

    user_name = cfg.USER_NAME
    user_portfolio = cfg.USER_PORTFOLIO
    user_github = cfg.USER_GITHUB
    user_skills = "Python, C/C++, TypeScript, Next.js, LangChain, LangGraph, Agentic AI, RAG, Qdrant, Mem0, Docker, SQL"
    user_bg = (
        "AI/ML & Full-Stack Developer | B.Tech CSE 2026 (CGPA 8.63) | 2x Hackathon Winner | GATE CS 2026 Qualified | "
        "AI Model Evaluator at Turing | AI & ML Mentor at TechNex | built production LangGraph Agentic AI platform & Aayojan.AI (Hackathon Winner)"
    )

    def _call_gemini_with_retry(prompt_text: str) -> str:
        """Call Gemini with simple manual retry on any error (429/503 safe)."""
        last_exc = None
        for attempt in range(4):
            try:
                resp = client.models.generate_content(
                    model=cfg.GEMINI_MODEL,
                    contents=prompt_text,
                )
                return resp.text
            except Exception as exc:
                last_exc = exc
                wait_secs = 5 * (2 ** attempt)  # 5, 10, 20, 40 seconds
                logger.warning(
                    f"Gemini attempt {attempt + 1}/4 failed: {exc}. "
                    f"Retrying in {wait_secs}s..."
                )
                time.sleep(wait_secs)
        raise last_exc

    BATCH_SIZE = 5
    for batch_start in range(0, len(contacts), BATCH_SIZE):
        batch = contacts[batch_start: batch_start + BATCH_SIZE]

        # Clean contacts (handle CSV where name is serial index and company is person's name)
        cleaned_batch = []
        for i, c in enumerate(batch):
            cleaned = _clean_contact_fields(c)
            cleaned["id"] = i
            cleaned_batch.append(cleaned)

        contacts_json = json.dumps([
            {
                "id": c["id"],
                "to_name": c["person_name"],
                "to_designation": c["designation"],
                "company": c["company"],
                "email": c["email"],
            }
            for c in cleaned_batch
        ], indent=2)

        prompt = f"""You are {user_name}, a {user_bg} skilled in {user_skills}.
Write SHORT, CRISP personalized cold emails to these HR/Hiring managers.

Rules:
- Each email unique and personalized using the person's name, designation, and company
- Subject line: short, compelling (max 10 words)
- Body: max 5-6 lines total. Greeting, 1-2 line intro, specific value prop, CTA.
- Tone: confident yet warm, direct (not nervous or overly humble)
- NO clich\u00e9s: skip \"I hope\", \"thrilled\", \"esteemed\", \"please find\", \"keen interest\"
- Always mention resume is attached
- ALWAYS end every email with exactly:
  Portfolio: {cfg.USER_PORTFOLIO} | GitHub: {cfg.USER_GITHUB}
  Best regards,
  {user_name}

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
                        "subject": item.get("subject", "Opportunity to connect -- Fresher CSE"),
                        "body": item.get("body", ""),
                    })

            logger.info(f"Generated {len(batch_results)} PDF emails (batch {batch_start // BATCH_SIZE + 1})")

        except json.JSONDecodeError as e:
            logger.warning(f"Gemini JSON parse error for PDF email batch: {e}. Using fallback.")
            for c in batch:
                results.append(_fallback_email(c, user_name, user_skills))

        except Exception as e:
            logger.error(f"Gemini call failed for PDF email batch after retries: {e}. Using fallback.")
            for c in batch:
                results.append(_fallback_email(c, user_name, user_skills))

        # Rate limit buffer -- 4s to reduce 429 pressure
        time.sleep(4)

    return results


def _clean_contact_fields(contact: Dict) -> Dict:
    """Normalize contact fields from CSV."""
    raw_name = contact.get("name", "").strip()
    raw_company = contact.get("company", "").strip()
    designation = contact.get("designation", "HR").strip()
    email = contact.get("email", "").strip()

    # In CSV, if name is an index number (e.g. '1397'), person's name was placed in company
    if raw_name.isdigit() and raw_company and not raw_company.isdigit():
        person_name = raw_company
        domain = email.split("@")[-1] if "@" in email else ""
        company = domain.split(".")[0].capitalize() if domain else "your team"
    else:
        person_name = raw_name if (raw_name and not raw_name.isdigit()) else "Hiring Manager"
        company = raw_company or "your team"

    # Clean title keywords if company looks like a title
    HR_TITLE_KEYWORDS = ["director", "manager", "recruiter", "vp", "head of", "officer", "talent"]
    if any(kw in company.lower() for kw in HR_TITLE_KEYWORDS):
        domain = email.split("@")[-1] if "@" in email else ""
        company = domain.split(".")[0].capitalize() if domain else "your company"

    return {
        "person_name": person_name,
        "company": company,
        "designation": designation,
        "email": email,
    }


def _fallback_email(contact: Dict, user_name: str, user_skills: str) -> Dict:
    """Fallback email template if Gemini fails."""
    c = _clean_contact_fields(contact)
    name = c["person_name"]
    company = c["company"]
    designation = c["designation"]
    email = c["email"]

    greeting = f"Hi {name}," if name and name.lower() not in ["", "unknown", "n/a", "hiring manager"] else "Hi there,"

    body = f"""{greeting}

I'm Debashis Bera — AI/ML & Full-Stack Developer (B.Tech CSE 2026, GATE CS 2026 Qualified, 2x Hackathon Winner). I have hands-on experience evaluating LLM models at Turing, mentoring AI/ML at TechNex, and building production Agentic AI platforms with Python, LangGraph, and Next.js.

I'm reaching out to explore AI/ML and Software Engineering opportunities at {company}. My resume is attached with full project details.

Portfolio: {cfg.USER_PORTFOLIO} | GitHub: {cfg.USER_GITHUB}
Best regards,
{user_name}"""

    return {
        "to_email": email,
        "subject": f"AI/ML & Full-Stack Developer | GATE Qualified | {company}",
        "body": body,
    }
