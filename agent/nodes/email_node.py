"""
agent/nodes/email_node.py — HR email finding + cold email generation + sending

Anti-429 strategy:
- All cold emails generated in BATCHES of 5 per Gemini call
- Template-based with LLM only filling in personalizations
- 30-second delay between each email send (anti-spam)
"""
import json
import time
import logging
import random
from typing import Dict, List
from agent.state import AgentState
from database.db_manager import DatabaseManager
from tools.email_finder import find_hr_email
from tools.email_sender import EmailSender
import config as cfg

logger = logging.getLogger(__name__)


def email_node(state: AgentState) -> Dict:
    """
    LangGraph node: Find HR emails + generate + send personalized cold emails.
    
    Strategy:
    1. For ALL jobs today (applied + manual_required), find HR email
    2. Generate personalized cold emails in batches (5 per Gemini call)
    3. Send with 30s delay between each
    """
    dry_run = state.get("dry_run", True)
    db = DatabaseManager(cfg.DB_PATH)
    application_results = state.get("application_results", [])
    scored_jobs = state.get("scored_jobs", [])

    emails_sent = []
    emails_to_send = []

    # Prioritize all scored jobs today up to the daily email limit
    all_jobs_today = scored_jobs[:cfg.MAX_EMAIL_PER_DAY]

    if not all_jobs_today:
        logger.info("No jobs for email outreach today")
        return {"emails_sent": [], "total_emailed": 0}

    # ── Step 1: Find HR emails ─────────────────────────────────────────
    jobs_with_emails = []
    seen_companies = set()  # avoid emailing same company twice

    for job in all_jobs_today:
        company = job.get("company", "")
        if not company:
            continue

        # Skip duplicate companies (same company listed multiple times)
        company_key = company.lower().strip()
        if company_key in seen_companies:
            continue
        seen_companies.add(company_key)

        logger.info(f"Finding HR email for: {company}")
        hr_data = find_hr_email(company, job.get("url", ""))  # pass URL for domain extraction

        if hr_data.get("email"):
            job["hr_email"] = hr_data["email"]
            job["hr_domain"] = hr_data.get("domain", "")
            job["hr_confidence"] = hr_data.get("confidence", "low")
            jobs_with_emails.append(job)
            # Store in DB
            db.add_hr_contact(
                company=company,
                domain=hr_data.get("domain", ""),
                hr_name="HR Team",
                email=hr_data["email"],
                source=hr_data.get("source", "unknown")
            )

        time.sleep(random.uniform(0.5, 1.5))  # shorter rate limit

    logger.info(f"Found HR emails for {len(jobs_with_emails)}/{len(all_jobs_today)} companies")

    # ── Step 2: Generate personalized emails in batches ────────────────
    batch_size = cfg.EMAIL_BATCH_SIZE  # 5 per Gemini call
    for i in range(0, len(jobs_with_emails), batch_size):
        batch = jobs_with_emails[i:i + batch_size]
        generated = _generate_email_batch(batch)
        emails_to_send.extend(generated)

        # Rate limit between Gemini calls
        if i + batch_size < len(jobs_with_emails):
            time.sleep(cfg.GEMINI_DELAY_BETWEEN_CALLS)

    # ── Step 3: Send emails ────────────────────────────────────────────
    sender = EmailSender(
        gmail_address=cfg.GMAIL_ADDRESS,
        app_password=cfg.GMAIL_APP_PASSWORD,
        resume_path=cfg.RESUME_PATH,
    )

    sent_count = 0
    for email_data in emails_to_send:
        if sent_count >= cfg.MAX_EMAIL_PER_DAY:
            logger.info(f"Reached daily email limit ({cfg.MAX_EMAIL_PER_DAY})")
            break

        success = sender.send_cold_email(
            to_email=email_data["to_email"],
            subject=email_data["subject"],
            body=email_data["body"],
            dry_run=dry_run,
        )

        if success:
            sent_count += 1
            emails_sent.append(email_data)
            # Update DB
            db.mark_email_sent(email_data["job_url"], email_data["to_email"])

        # 30 second delay between emails (anti-spam)
        if not dry_run and sent_count < len(emails_to_send):
            logger.info("⏳ Waiting 30s before next email...")
            time.sleep(30)

    # Update daily stats
    db.update_daily_stats(
        state.get("run_date", ""),
        total_emailed=sent_count
    )

    logger.info(f"✅ Email node: {sent_count} cold emails sent")

    return {
        "emails_to_send": emails_to_send,
        "emails_sent": emails_sent,
        "total_emailed": sent_count,
    }


def _generate_email_batch(jobs: List[dict]) -> List[dict]:
    """
    Generate personalized cold emails for a batch of jobs.
    Single Gemini call for all jobs in the batch.
    """
    from google import genai
    from tenacity import retry, stop_after_attempt, wait_exponential

    client = genai.Client(api_key=cfg.GEMINI_API_KEY)

    # Build compact job info
    job_infos = []
    for i, job in enumerate(jobs):
        job_infos.append({
            "id": i,
            "title": job.get("title", "")[:80],
            "company": job.get("company", ""),
            "hr_email": job.get("hr_email", ""),
            "job_url": job.get("url", ""),
            "portal": job.get("portal", ""),
            "desc_snippet": job.get("description", "")[:200],
        })

    user_name = cfg.USER_NAME
    user_phone = cfg.USER_PHONE
    user_portfolio = cfg.USER_PORTFOLIO
    user_github = cfg.USER_GITHUB
    user_linkedin = cfg.USER_LINKEDIN
    
    # Key skills summary for context
    skills_summary = (
        f"Python, C++, AI/ML, LangChain, Generative AI, Agentic AI, "
        f"SQL, HTML/CSS, JavaScript"
    )
    
    # Best project for reference
    best_project = cfg.PROJECTS[0] if cfg.PROJECTS else {"name": "AI Agent", "description": "LLM-powered automation"}

    prompt = f"""Generate {len(jobs)} personalized cold job application emails.

Applicant: {user_name}
Skills: {skills_summary}
Best Project: {best_project['name']} — {best_project['description']}
Portfolio: {user_portfolio}
GitHub: {user_github}
LinkedIn: {user_linkedin}
Phone: {user_phone}
Status: Final year B.Tech CSE student, strong in Python/AI/ML/GenAI

RULES FOR EACH EMAIL:
- Must start with "Hey [HR Name / Hiring Team]," or "Hey team," — NEVER start with "Hi", "Dear", or "Respected".
- Extremely human-sounding, short, crisp, impressive, and deeply personalized based on the specific job description and company context.
- Absolutely NO robotic AI-generated markers or corporate clichés (do NOT use "I hope this email finds you well", "thrilled to apply", "esteemed organization", "delighted to submit", "please find my resume attached", "keen interest").
- Write like a highly competent, confident developer student reaching out directly.
- The email body length should be natural and fully custom-personalized to the JD, ranging from 4-5 lines up to 9-10 lines if needed for rich technical mapping.
- Focus on 1-2 skills or project highlights that directly map to the JD.
- End with: Portfolio: {user_portfolio} | GitHub: {user_github}
- Sign off as {user_name}

Jobs to email about:
{json.dumps(job_infos, indent=2)}

Return ONLY valid JSON array:
[
  {{
    "id": 0,
    "subject": "Application for [Role] — Fresher | {user_name}",
    "body": "Hey [HR Name / Hiring Team],\\n\\n[email body]\\n\\nBest,\\n{user_name}\\n{user_phone}"
  }},
  ...
]
No markdown, no explanations. Just the JSON array."""

    @retry(
        wait=wait_exponential(multiplier=2, min=5, max=60),
        stop=stop_after_attempt(3)
    )
    def call_gemini():
        response = client.models.generate_content(
            model=cfg.GEMINI_MODEL,
            contents=prompt
        )
        return response.text

    try:
        response_text = call_gemini()

        # Clean markdown if present
        clean = response_text.strip()
        if "```" in clean:
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]

        email_data = json.loads(clean)

        # Map back to full job info
        results = []
        for item in email_data:
            idx = item.get("id", 0)
            if idx < len(jobs):
                job = jobs[idx]
                results.append({
                    "job_url": job.get("url", ""),
                    "to_email": job.get("hr_email", ""),
                    "subject": item.get("subject", f"Job Application — {user_name}"),
                    "body": item.get("body", ""),
                    "company": job.get("company", ""),
                    "job_title": job.get("title", ""),
                })

        logger.info(f"✅ Generated {len(results)} emails in 1 Gemini call")
        return results

    except Exception as e:
        logger.error(f"Email generation failed: {e}")
        # Fallback: use template
        return _fallback_email_template(jobs)


def _fallback_email_template(jobs: List[dict]) -> List[dict]:
    """Simple template-based email fallback (no LLM needed)."""
    results = []
    for job in jobs:
        body = f"""Hey Hiring Team,

I am {cfg.USER_NAME}, a final year B.Tech CSE student with strong skills in Python, AI/ML, Generative AI, and C++. I saw the {job.get('title', 'position')} opening at {job.get('company', 'your company')} and wanted to reach out.

Key highlights of my background:
• Python, C++, LangChain, LangGraph, Gemini API, Machine Learning
• Developed: {cfg.PROJECTS[0]['name'] if cfg.PROJECTS else 'AI automation projects'} — {cfg.PROJECTS[0]['description'] if cfg.PROJECTS else 'automation workflows'}
• Portfolio: {cfg.USER_PORTFOLIO}
• GitHub: {cfg.USER_GITHUB}

My resume is attached. I would love to connect for a quick call to discuss how I can contribute.

Best,
{cfg.USER_NAME}
{cfg.USER_PHONE} | {cfg.GMAIL_ADDRESS}"""

        results.append({
            "job_url": job.get("url", ""),
            "to_email": job.get("hr_email", ""),
            "subject": f"Application for {job.get('title', 'Software Role')} — Fresher | {cfg.USER_NAME}",
            "body": body,
            "company": job.get("company", ""),
            "job_title": job.get("title", ""),
        })

    return results
