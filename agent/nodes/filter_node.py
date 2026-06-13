"""
agent/nodes/filter_node.py — Deduplication, keyword filtering, and LLM-based scoring

Anti-429 strategy:
- All job scoring done in a SINGLE batched Gemini call
- Jobs truncated to 150 chars before sending to LLM
- Exponential backoff on 429 errors
"""
import json
import time
import logging
from typing import Dict, List
from agent.state import AgentState
from database.db_manager import DatabaseManager
import config as cfg

logger = logging.getLogger(__name__)


def filter_deduplicate_node(state: AgentState) -> Dict:
    """
    LangGraph node: Remove duplicates + filter by relevance keywords.
    Uses SQLite to check if job was already seen/applied.
    """
    db = DatabaseManager(cfg.DB_PATH)
    raw_jobs = state.get("raw_jobs", [])
    new_jobs = []
    seen_urls = set()

    for job in raw_jobs:
        url = job.get("url", "")
        if not url or url in seen_urls:
            continue

        # Check against database (already applied/seen)
        if db.is_already_seen(url):
            logger.debug(f"Skip (already seen): {job.get('title')} @ {job.get('company')}")
            continue

        # Basic keyword filter
        if not _is_relevant_job(job):
            logger.debug(f"Skip (not relevant): {job.get('title')}")
            continue

        seen_urls.add(url)
        new_jobs.append(job)

        # Add to DB as "new" (not yet applied)
        db.add_job(job)

    logger.info(f"✅ Filter: {len(raw_jobs)} scraped → {len(new_jobs)} new relevant jobs")

    # Update daily stats with today's new jobs count in real time
    try:
        from datetime import datetime
        run_date = state.get("run_date") or datetime.now().strftime("%Y-%m-%d")
        db.update_daily_stats(run_date, total_new=len(new_jobs))
    except Exception as e:
        logger.warning(f"Failed to update daily stats for filter node: {e}")

    return {
        "new_jobs": new_jobs,
        "total_new": len(new_jobs),
    }


def _is_relevant_job(job: dict) -> bool:
    """Strict relevance check for tech-only roles (Python/AI/ML focused)."""
    title = job.get("title", "").lower()
    description = job.get("description", "").lower()

    # Blacklist keywords for title (non-tech roles + Java stack)
    blacklist = [
        "video", "editor", "graphic", "designer", "design", "electronics", 
        "electrical", "mechanical", "civil", "trainer", "organic", "store", 
        "ngo", "social", "foundation", "writer", "content", "marketing", 
        "recruiter", "sales", "bpo", "telecall", "telecaller", "support", 
        "desktop", "admin", "office", "accountant", "finance", "hr", "operations",
        # ── Java stack exclusions (as requested) ──
        "java developer", "java engineer", "java programmer", 
        "spring boot", "hibernate", "j2ee", "struts", "servlet",
        "android developer",  # Java/Kotlin, not Python AI
        ".net developer", "dotnet", "asp.net", "c# developer",
        "php developer", "laravel", "wordpress",
        "ruby on rails",
        "salesforce", "sap abap",
    ]

    # If any blacklist keyword is in the title, reject immediately
    for kw in blacklist:
        if kw in title:
            return False

    # Deep description check: if JD is EXCLUSIVELY java-focused with no Python/AI mention
    java_desc_heavy = (
        description.count("java") >= 3 and
        not any(kw in description for kw in ["python", "ai", "ml", "machine learning", "deep learning", "pytorch", "tensorflow", "langchain"])
    )
    if java_desc_heavy:
        logger.debug(f"Skip (java-heavy JD): {job.get('title')}")
        return False

    # Whitelist keywords for tech roles
    tech_keywords = [
        "software", "python", "ai", "ml", "machine learning", "backend", 
        "full stack", "fullstack", "c++", "cpp", "generative", "gen ai", 
        "agentic", "data scientist", "data science", "llm", "nlp", 
        "deep learning", "computer vision", "programmer", "developer", "engineer"
    ]

    # Job title must contain at least one tech keyword, or be a generic fresher/intern role
    title_tech = any(kw in title for kw in tech_keywords)
    title_generic_fresher = any(kw in title for kw in ["intern", "fresher", "trainee", "associate"])
    desc_tech = any(kw in description for kw in tech_keywords)

    is_tech_role = title_tech or (title_generic_fresher and desc_tech)

    # Must NOT have senior experience requirements
    exclude_patterns = [
        "5+ years", "7+ years", "8+ years", "10+ years",
        "senior", "lead engineer", "principal", "director",
        "vp of", "head of engineering", "cto"
    ]
    text = title + " " + description
    is_senior = any(pat in text for pat in exclude_patterns)

    return is_tech_role and not is_senior


def score_and_rank_node(state: AgentState) -> Dict:
    """
    LangGraph node: Score jobs using Gemini Flash in a SINGLE batched call.
    Selects top MAX_APPLY_PER_DAY jobs for today.
    
    Token optimization:
    - All jobs sent in ONE prompt (not per-job calls)
    - Descriptions truncated to 150 chars
    - Returns JSON scores only
    """
    new_jobs = state.get("new_jobs", [])

    if not new_jobs:
        logger.info("No new jobs to score")
        return {"scored_jobs": [], "jobs_to_apply": []}

    # If fewer jobs than batch size, score all at once
    scored_jobs = _batch_score_with_gemini(new_jobs)

    # Sort by score descending
    scored_jobs.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    # ── Write scores back to DB so dashboard can display them ────────────
    try:
        import sqlite3
        with sqlite3.connect(cfg.DB_PATH) as conn:
            for job in scored_jobs:
                score = job.get("relevance_score", 0)
                url = job.get("url", "")
                if url:
                    job_hash = DatabaseManager.make_job_hash(url)
                    conn.execute(
                        "UPDATE applications SET relevance_score = ? WHERE job_hash = ?",
                        (score, job_hash)
                    )
    except Exception as db_err:
        logger.warning(f"Could not write scores to DB: {db_err}")

    # Select top N for today
    today_applied = DatabaseManager(cfg.DB_PATH).get_today_applied_count()
    remaining_quota = max(0, cfg.MAX_APPLY_PER_DAY - today_applied)
    jobs_to_apply = scored_jobs[:remaining_quota]

    logger.info(
        f"Scored {len(scored_jobs)} jobs. "
        f"Selecting top {len(jobs_to_apply)} for today "
        f"(quota: {remaining_quota} remaining)"
    )

    return {
        "scored_jobs": scored_jobs,
        "jobs_to_apply": jobs_to_apply,
    }


def _batch_score_with_gemini(jobs: List[dict]) -> List[dict]:
    """
    Score all jobs in a single Gemini call.
    Returns jobs list with relevance_score added.
    """
    from google import genai
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

    client = genai.Client(api_key=cfg.GEMINI_API_KEY)

    # Build compact job list for the prompt (truncate descriptions to save tokens)
    compact_jobs = []
    for i, job in enumerate(jobs):
        compact_jobs.append({
            "id": i,
            "title": job.get("title", "")[:80],
            "company": job.get("company", "")[:50],
            "desc": job.get("description", "")[:150],
            "portal": job.get("portal", ""),
        })

    user_skills = ", ".join(cfg.SKILLS.get("languages", []) + cfg.SKILLS.get("ai_ml", []))

    prompt = f"""You are scoring job listings for a fresher CSE student.

Student skills: {user_skills}
Student background: Final year B.Tech CSE, no work experience, strong in Python, C++, AI/ML, Gen AI, Agentic AI.

Score each job 0-10 where:
- 10 = Perfect match (Python/AI/ML/GenAI, explicitly fresher/0-1yr, entry level)
- 7-9 = Good match (relevant role, probably accepts freshers)
- 4-6 = Okay match (software role but less relevant skills)
- 0-3 = Bad match (senior role, irrelevant field, or heavy experience required)

Jobs to score:
{json.dumps(compact_jobs, indent=2)}

Return ONLY valid JSON array: [{{"id": 0, "score": 8.5}}, ...]
No explanations, no markdown, just JSON."""

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=2, min=4, max=60),
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

        # Parse JSON response
        # Clean up response in case of markdown code blocks
        clean = response_text.strip()
        if "```" in clean:
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]

        scores = json.loads(clean)
        score_map = {item["id"]: item["score"] for item in scores}

        # Apply scores to original jobs
        for i, job in enumerate(jobs):
            job["relevance_score"] = score_map.get(i, 5.0)

        logger.info(f"Gemini scored {len(jobs)} jobs in 1 API call")

    except json.JSONDecodeError as e:
        logger.warning(f"Gemini score parsing failed: {e}. Using default scores.")
        for job in jobs:
            job["relevance_score"] = 5.0
    except Exception as e:
        logger.error(f"Gemini scoring error: {e}. Using default scores.", exc_info=True)
        for job in jobs:
            job["relevance_score"] = 5.0

    return jobs
