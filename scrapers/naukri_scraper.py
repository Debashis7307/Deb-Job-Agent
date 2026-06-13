"""
scrapers/naukri_scraper.py — Naukri.com fresher job scraper using Playwright
"""
import asyncio
import random
import logging
from typing import List, Dict
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

NAUKRI_SEARCH_CONFIGS = [
    {"keyword": "python developer", "experience": "0", "location": ""},
    {"keyword": "software engineer fresher", "experience": "0", "location": ""},
    {"keyword": "machine learning engineer", "experience": "0", "location": ""},
    {"keyword": "AI engineer", "experience": "0", "location": ""},
    {"keyword": "data scientist fresher", "experience": "0", "location": ""},
    {"keyword": "c++ developer fresher", "experience": "0", "location": ""},
    {"keyword": "full stack developer fresher", "experience": "0", "location": ""},
]


async def scrape_naukri_async(
    email: str, password: str, max_jobs: int = 30, dry_run: bool = True
) -> List[Dict]:
    """Scrape Naukri.com for fresher jobs using Playwright."""
    try:
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth
    except ImportError:
        logger.error("playwright not installed")
        return []

    jobs = []
    seen_urls = set()

    async with async_playwright() as p:
        import config as cfg
        browser = await p.chromium.launch(
            headless=cfg.BROWSER_HEADLESS,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)

        # ── Login ──────────────────────────────────────────────────────
        if email and password and not dry_run:
            try:
                logger.info("Naukri: Logging in...")
                await page.goto("https://www.naukri.com/nlogin/login", wait_until="domcontentloaded")
                await asyncio.sleep(random.uniform(2, 3))

                # Wait for username field with robust fallbacks
                username_selector = "#usernameField, input[name='username'], input[placeholder*='Email'], input[placeholder*='Username']"
                await page.wait_for_selector(username_selector, timeout=10000)
                await page.fill(username_selector, email)
                await asyncio.sleep(random.uniform(0.5, 1))

                password_selector = "#passwordField, input[name='password'], input[placeholder*='password']"
                await page.fill(password_selector, password)
                await asyncio.sleep(random.uniform(0.5, 1))

                submit_selector = "button[type='submit'], button.btn-primary, button.login-button"
                await page.click(submit_selector)
                await asyncio.sleep(random.uniform(3, 5))

                logger.info("Naukri: Login done")
            except Exception as e:
                logger.warning(f"Naukri login failed: {e}")

        # ── Search Jobs ────────────────────────────────────────────────
        for config in NAUKRI_SEARCH_CONFIGS:
            if len(jobs) >= max_jobs:
                break

            search_url = _build_naukri_url(config)
            try:
                logger.info(f"Naukri: Searching '{config['keyword']}'")
                await page.goto(search_url, wait_until="domcontentloaded")
                await asyncio.sleep(random.uniform(3, 5))

                # Scroll to load jobs
                for _ in range(2):
                    await page.keyboard.press("End")
                    await asyncio.sleep(1.5)

                # Get job cards (supports both old and new layouts)
                cards = await page.query_selector_all("article.jobTuple, div.srp-jobtuple-wrapper, div.cust-job-tuple")

                for card in cards[:10]:
                    try:
                        job = await _extract_naukri_job(card)
                        if job and job["url"] not in seen_urls:
                            seen_urls.add(job["url"])
                            jobs.append(job)
                    except Exception as e:
                        logger.debug(f"Naukri card error: {e}")

            except Exception as e:
                logger.error(f"Naukri search failed for '{config['keyword']}': {e}")

            await asyncio.sleep(random.uniform(4, 7))

        await browser.close()

    logger.info(f"Naukri: Found {len(jobs)} jobs")
    return jobs


async def _extract_naukri_job(card) -> Dict:
    """Extract job details from a Naukri job card."""
    title_el = await card.query_selector("a.title")
    company_el = await card.query_selector("a.subTitle, a.comp-name")
    location_el = await card.query_selector("li.location span, span.loc")
    experience_el = await card.query_selector("li.experience span, span.exp")
    salary_el = await card.query_selector("li.salary span, span.sal")

    title = (await title_el.inner_text()).strip() if title_el else ""
    company = (await company_el.inner_text()).strip() if company_el else ""
    location = (await location_el.inner_text()).strip() if location_el else "India"
    experience = (await experience_el.inner_text()).strip() if experience_el else ""
    salary = (await salary_el.inner_text()).strip() if salary_el else ""
    href = await title_el.get_attribute("href") if title_el else ""

    if not title or not href:
        return None

    return {
        "title": title,
        "company": company,
        "location": location,
        "url": href,
        "description": f"{title} at {company}. Experience: {experience}. Salary: {salary}",
        "portal": "naukri",
        "experience_required": experience,
        "salary": salary,
        "is_us_remote": False,
    }


def _build_naukri_url(config: dict) -> str:
    """Build Naukri search URL."""
    keyword_slug = config["keyword"].replace(" ", "-")
    return (
        f"https://www.naukri.com/{keyword_slug}-jobs"
        f"?experience={config.get('experience', '0')}"
        f"&jobAge=1"  # Last 1 day
    )


def scrape_naukri(email: str, password: str, max_jobs: int = 30, dry_run: bool = True) -> List[Dict]:
    """Synchronous wrapper for Naukri async scraper."""
    return asyncio.run(scrape_naukri_async(email, password, max_jobs, dry_run))
