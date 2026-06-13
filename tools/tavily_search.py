"""
tools/tavily_search.py — Tavily real-time internet search for the Job Agent

Uses Tavily API for:
1. HR email discovery   — find founder/HR emails for a company
2. Startup job hunting  — search Reddit, YC, AngelList for fresh job postings  
3. Free job portals     — search additional job boards not scraped natively
4. Founder profiles     — find founder names, LinkedIn profiles, direct emails

Tavily free plan: ~1,000 searches/month → max 15/day budget (enforced via SQLite).
"""
import logging
import sqlite3
import time
from datetime import date
from typing import List, Dict, Optional
import config as cfg

logger = logging.getLogger(__name__)

# ── Free job portals Tavily will scan beyond the core scrapers ─────────────
FREE_JOB_PORTAL_QUERIES = [
    "site:remotive.com python OR AI OR ML engineer job 2025",
    "site:jobspresso.co python developer OR AI engineer job remote",
    "site:himalayas.app python AI ML engineer fresher remote job",
    "site:otta.com python OR machine learning engineer entry level",
    "site:workatastartup.com python AI engineer 0 years experience",
    "site:angel.co/jobs python AI ML fresher engineer remote",
    "site:startup.jobs python AI ML developer remote 2025",
    "site:freshersworld.com python developer fresher job",
    "site:cutshort.io python AI engineer fresher job",
]


def _get_db_conn():
    conn = sqlite3.connect(cfg.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_tavily_table():
    """Create tavily_usage table if not exists."""
    try:
        with _get_db_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tavily_usage (
                    date TEXT PRIMARY KEY,
                    count INTEGER DEFAULT 0
                )
            """)
    except Exception as e:
        logger.debug(f"Tavily table init: {e}")


def get_today_tavily_count() -> int:
    """Return how many Tavily searches we've done today."""
    _init_tavily_table()
    today = date.today().isoformat()
    try:
        with _get_db_conn() as conn:
            row = conn.execute(
                "SELECT count FROM tavily_usage WHERE date = ?", (today,)
            ).fetchone()
        return row["count"] if row else 0
    except Exception:
        return 0


def _increment_tavily_count(n: int = 1):
    """Increment today's Tavily usage counter."""
    today = date.today().isoformat()
    try:
        with _get_db_conn() as conn:
            existing = conn.execute(
                "SELECT count FROM tavily_usage WHERE date = ?", (today,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE tavily_usage SET count = count + ? WHERE date = ?", (n, today)
                )
            else:
                conn.execute(
                    "INSERT INTO tavily_usage (date, count) VALUES (?, ?)", (today, n)
                )
    except Exception as e:
        logger.debug(f"Tavily count increment error: {e}")


def _call_tavily(query: str, max_results: int = 5, search_depth: str = "basic") -> List[Dict]:
    """
    Core Tavily API call. Returns list of result dicts.
    search_depth: "basic" (fast, free) or "advanced" (slower, uses more credits).
    """
    if not cfg.USE_TAVILY:
        return []

    today_count = get_today_tavily_count()
    if today_count >= cfg.TAVILY_DAILY_LIMIT:
        logger.info(f"Tavily daily limit reached ({today_count}/{cfg.TAVILY_DAILY_LIMIT}). Skipping.")
        return []

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=cfg.TAVILY_API_KEY)

        response = client.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_answer=False,
            include_raw_content=False,
        )
        results = response.get("results", [])
        _increment_tavily_count(1)
        logger.debug(f"Tavily: '{query[:60]}' → {len(results)} results (today: {today_count+1}/{cfg.TAVILY_DAILY_LIMIT})")
        return results

    except ImportError:
        logger.warning("Tavily not installed. Run: pip install tavily-python")
        return []
    except Exception as e:
        logger.warning(f"Tavily search error for '{query[:50]}': {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════
# 1. HR & FOUNDER EMAIL DISCOVERY
# ══════════════════════════════════════════════════════════════════════════

import re
EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
BAD_EMAIL_DOMAINS = {"example.com", "test.com", "gmail.com", "yahoo.com",
                     "hotmail.com", "outlook.com", "protonmail.com"}


def search_founder_hr_email(company_name: str, domain: str) -> Optional[str]:
    """
    Use Tavily to find a real founder/HR/recruiter email for a company.
    Searches LinkedIn profiles, startup news, contact pages.
    Returns first verified email found, or None.
    """
    queries = [
        f'"{company_name}" founder OR CEO OR "head of engineering" email @{domain}',
        f'"{company_name}" HR manager OR recruiter OR "talent acquisition" email',
        f'site:linkedin.com/in "{company_name}" founder OR HR email contact',
    ]

    emails_found = []
    for query in queries[:2]:  # Use max 2 searches per company to conserve quota
        results = _call_tavily(query, max_results=5)
        for r in results:
            # Search content for email patterns
            text = (r.get("content", "") + " " + r.get("url", "")).lower()
            found = EMAIL_RE.findall(r.get("content", ""))
            for email in found:
                email_lower = email.lower()
                domain_part = email_lower.split("@")[-1]
                if (domain_part not in BAD_EMAIL_DOMAINS and
                        (domain in domain_part or domain_part in domain)):
                    emails_found.append(email_lower)

        if emails_found:
            break

    if emails_found:
        # Prefer HR/careers/founder keywords
        preferred = [e for e in emails_found if any(
            kw in e for kw in ["hr", "recruit", "hiring", "careers", "talent", "founder", "ceo"]
        )]
        result = preferred[0] if preferred else emails_found[0]
        logger.info(f"Tavily found email for {company_name}: {result}")
        return result

    return None


# ══════════════════════════════════════════════════════════════════════════
# 2. STARTUP JOB DISCOVERY (Reddit, YC, AngelList, etc.)
# ══════════════════════════════════════════════════════════════════════════

def search_startup_jobs(role_keywords: str = "python AI ML engineer fresher") -> List[Dict]:
    """
    Search Reddit, YC, AngelList, Hacker News for fresh job postings.
    Returns list of job dicts.
    """
    jobs = []
    queries = [
        f'site:reddit.com/r/forhire OR r/jobbit OR r/cscareerquestions "{role_keywords}" hiring 2025',
        f'site:news.ycombinator.com "who is hiring" {role_keywords} 2025',
        f'"{role_keywords}" remote job posting site:workatastartup.com OR site:otta.com 2025',
    ]

    for query in queries[:2]:
        results = _call_tavily(query, max_results=5, search_depth="basic")
        for r in results:
            url = r.get("url", "")
            title = r.get("title", "")
            content = r.get("content", "")
            if url and title:
                jobs.append({
                    "title": title[:120],
                    "company": "Startup/Reddit",
                    "location": "Remote",
                    "url": url,
                    "description": content[:800],
                    "portal": "tavily_web",
                    "is_easy_apply": False,
                    "is_us_remote": True,
                    "source": "tavily_startup_search",
                })
        time.sleep(0.5)  # brief pause between searches

    logger.info(f"Tavily startup job search: found {len(jobs)} leads")
    return jobs


# ══════════════════════════════════════════════════════════════════════════
# 3. FREE JOB PORTAL SCANNER
# ══════════════════════════════════════════════════════════════════════════

def search_free_job_portals(max_portals: int = 3) -> List[Dict]:
    """
    Search additional free job portals (Remotive, Himalayas, Otta, etc.)
    that the agent doesn't scrape natively.
    Returns structured job listings.
    """
    jobs = []
    today_count = get_today_tavily_count()
    searches_available = min(max_portals, cfg.TAVILY_DAILY_LIMIT - today_count)

    if searches_available <= 0:
        logger.info("Tavily: No budget left for portal search today.")
        return []

    for query in FREE_JOB_PORTAL_QUERIES[:searches_available]:
        results = _call_tavily(query, max_results=5)
        for r in results:
            url = r.get("url", "")
            title = r.get("title", "")
            content = r.get("content", "")
            if not url or not title:
                continue

            # Detect company from title (usually "Company — Role | Portal")
            company = "Unknown"
            for sep in [" | ", " — ", " - ", " at ", " @ "]:
                if sep in title:
                    parts = title.split(sep)
                    if len(parts) >= 2:
                        company = parts[-1].strip()[:60]
                        title = parts[0].strip()[:120]
                        break

            jobs.append({
                "title": title,
                "company": company,
                "location": "Remote",
                "url": url,
                "description": content[:800],
                "portal": "tavily_web",
                "is_easy_apply": False,
                "is_us_remote": True,
                "source": "tavily_portal_search",
            })
        time.sleep(0.3)

    logger.info(f"Tavily free portal search: found {len(jobs)} jobs")
    return jobs


# ══════════════════════════════════════════════════════════════════════════
# 4. COMPANY RESEARCH (for personalized email context)
# ══════════════════════════════════════════════════════════════════════════

def research_company(company_name: str) -> Dict:
    """
    Get quick research snippets about a company for email personalization.
    Returns dict with: tagline, recent_news, tech_stack hints.
    Costs 1 Tavily search.
    """
    query = f'"{company_name}" company about tech stack recent news OR product 2024 OR 2025'
    results = _call_tavily(query, max_results=3, search_depth="basic")

    info = {"tagline": "", "recent_news": "", "tech_stack": ""}
    if results:
        snippets = [r.get("content", "")[:300] for r in results[:2]]
        info["recent_news"] = " ".join(snippets)[:500]

    return info
