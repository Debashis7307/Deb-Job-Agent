"""
agent/nodes/scrape_node.py — Orchestrates all job portal scrapers
Runs all scrapers and combines results into a unified list.
"""
import logging
from datetime import datetime
from typing import Dict
from agent.state import AgentState

logger = logging.getLogger(__name__)


def scrape_jobs_node(state: AgentState) -> Dict:
    """
    LangGraph node: Scrape all job portals and combine results.
    
    Portals scraped:
    - RemoteOK (free API, no login)
    - Internshala (BeautifulSoup, no login)
    - LinkedIn (Playwright + stealth, login required)
    - Naukri (Playwright + stealth, login required)
    - Wellfound (Playwright, no login)
    - Tavily Web Search (Remotive, Himalayas, Otta, Reddit jobs, YC HN, etc.)
    """
    import config as cfg

    all_jobs = []
    errors = []

    # ── 1. RemoteOK (always run — free API) ───────────────────────────
    try:
        from scrapers.remoteok_scraper import scrape_remoteok
        logger.info("📡 Scraping RemoteOK...")
        jobs = scrape_remoteok(max_jobs=30)
        all_jobs.extend(jobs)
        logger.info(f"✅ RemoteOK: {len(jobs)} jobs")
    except Exception as e:
        msg = f"RemoteOK failed: {e}"
        logger.error(msg)
        errors.append(msg)

    # ── 2. Internshala (no login needed) ──────────────────────────────
    try:
        from scrapers.internshala_scraper import scrape_internshala
        logger.info("📡 Scraping Internshala...")
        jobs = scrape_internshala(max_jobs=30)
        all_jobs.extend(jobs)
        logger.info(f"✅ Internshala: {len(jobs)} jobs")
    except Exception as e:
        msg = f"Internshala failed: {e}"
        logger.error(msg)
        errors.append(msg)

    # ── 3. Wellfound (no login needed) ────────────────────────────────
    try:
        from scrapers.wellfound_scraper import scrape_wellfound
        logger.info("📡 Scraping Wellfound...")
        jobs = scrape_wellfound(max_jobs=20)
        all_jobs.extend(jobs)
        logger.info(f"✅ Wellfound: {len(jobs)} jobs")
    except Exception as e:
        msg = f"Wellfound failed: {e}"
        logger.error(msg)
        errors.append(msg)

    # ── 3b. We Work Remotely (no login needed) ────────────────────────
    try:
        from scrapers.weworkremotely_scraper import scrape_weworkremotely
        logger.info("📡 Scraping We Work Remotely...")
        jobs = scrape_weworkremotely(max_jobs=30)
        all_jobs.extend(jobs)
        logger.info(f"✅ We Work Remotely: {len(jobs)} jobs")
    except Exception as e:
        msg = f"We Work Remotely failed: {e}"
        logger.error(msg)
        errors.append(msg)

    # ── 4. LinkedIn (requires login) ──────────────────────────────────
    if cfg.USE_LINKEDIN:
        try:
            from scrapers.linkedin_scraper import scrape_linkedin
            logger.info("📡 Scraping LinkedIn...")
            jobs = scrape_linkedin(
                email=cfg.LINKEDIN_EMAIL,
                password=cfg.LINKEDIN_PASSWORD,
                max_jobs=30,
                dry_run=state.get("dry_run", True)
            )
            all_jobs.extend(jobs)
            logger.info(f"✅ LinkedIn: {len(jobs)} jobs")
        except Exception as e:
            msg = f"LinkedIn failed: {e}"
            logger.error(msg)
            errors.append(msg)
    else:
        logger.info("⏭️ LinkedIn skipped (no credentials)")

    # ── 5. Naukri (requires login) ────────────────────────────────────
    if cfg.USE_NAUKRI:
        try:
            from scrapers.naukri_scraper import scrape_naukri
            logger.info("📡 Scraping Naukri...")
            jobs = scrape_naukri(
                email=cfg.NAUKRI_EMAIL,
                password=cfg.NAUKRI_PASSWORD,
                max_jobs=30,
                dry_run=state.get("dry_run", True)
            )
            all_jobs.extend(jobs)
            logger.info(f"✅ Naukri: {len(jobs)} jobs")
        except Exception as e:
            msg = f"Naukri failed: {e}"
            logger.error(msg)
            errors.append(msg)
    else:
        logger.info("⏭️ Naukri skipped (no credentials)")

    # ── 6. Tavily Free Job Portal Search ──────────────────────────────────
    if cfg.USE_TAVILY:
        try:
            from tools.tavily_search import (
                search_free_job_portals, search_startup_jobs, get_today_tavily_count
            )

            # IMPORTANT: Reserve 5 searches/day for HR email discovery.
            # Scrape phase only uses max 10 out of 15 daily budget.
            SCRAPE_TAVILY_BUDGET = min(10, cfg.TAVILY_DAILY_LIMIT - 5)
            already_used = get_today_tavily_count()
            scrape_budget_left = max(0, SCRAPE_TAVILY_BUDGET - already_used)

            if scrape_budget_left > 0:
                logger.info(f"Tavily: Searching free job portals & startup boards "
                            f"(budget: {scrape_budget_left} searches)...")
                tavily_jobs = search_free_job_portals(max_portals=min(3, scrape_budget_left))
                startup_jobs = search_startup_jobs() if scrape_budget_left >= 4 else []
                combined_tavily = tavily_jobs + startup_jobs

                # ── Filter: only include ACTUAL job postings, not portal listing pages ──
                # A real job posting URL usually has a specific path, not just a category page
                PORTAL_LIST_PATTERNS = [
                    "/jobs?role=", "/remote/jobs/", "/jobs/artificial-intelligence",
                    "/remote-jobs", "?category=", "/browse", "/search", "/listings",
                    "who-is-hiring", "who-wants-to-be-hired",
                    "/r/forhire", "/r/jobbit", "/r/cscareerquestions",
                    "jobs.ycombinator.com",  # YC jobs board root
                ]

                def _is_real_job_url(url: str) -> bool:
                    url_lower = url.lower()
                    # Reject obvious listing/category pages
                    for pat in PORTAL_LIST_PATTERNS:
                        if pat in url_lower:
                            return False
                    # Reject very short paths (portal home pages)
                    from urllib.parse import urlparse
                    path = urlparse(url).path.strip("/")
                    if len(path) < 10:  # e.g., jobspresso.co/ or remotive.com/remote/jobs
                        return False
                    return True

                real_jobs = []
                for job in combined_tavily:
                    url = job.get("url", "")
                    title = job.get("title", "")
                    # Filter out portal listing pages
                    if not _is_real_job_url(url):
                        logger.debug(f"Tavily: Skip listing page: {url[:80]}")
                        continue
                    # Filter out vague titles ("Best remote ... for hire in Jun 2026")
                    vague_patterns = [
                        "best remote", "employees for hire", "job openings",
                        "1,000+", "jobs in ", "remote jobs"
                    ]
                    if any(p in title.lower() for p in vague_patterns):
                        logger.debug(f"Tavily: Skip vague listing: {title[:60]}")
                        continue
                    # Mark as manual_apply (not auto-apply) — these link to external portals
                    job["portal"] = "tavily_link"
                    job["is_easy_apply"] = False
                    job["apply_type"] = "manual_link"  # Dashboard shows direct link
                    real_jobs.append(job)

                all_jobs.extend(real_jobs)
                logger.info(f"Tavily: {len(real_jobs)} real job leads (filtered from {len(combined_tavily)})")
            else:
                logger.info("Tavily: Scrape budget reserved for email discovery. Skipping portal scan today.")

        except Exception as e:
            msg = f"Tavily job search failed: {e}"
            logger.error(msg)
            errors.append(msg)
    else:
        logger.info("Tavily skipped (API key not configured)")


    logger.info(f"📊 Total scraped: {len(all_jobs)} jobs from all portals")

    # Update daily stats so the dashboard shows the real-time scraped count immediately
    try:
        from database.db_manager import DatabaseManager
        db = DatabaseManager(cfg.DB_PATH)
        run_date = state.get("run_date") or datetime.now().strftime("%Y-%m-%d")
        # Initialize or update stats for today
        db.update_daily_stats(run_date, total_scraped=len(all_jobs))
    except Exception as e:
        logger.warning(f"Failed to update daily stats for scrape node: {e}")

    return {
        "raw_jobs": all_jobs,
        "total_scraped": len(all_jobs),
        "errors": errors,
    }
