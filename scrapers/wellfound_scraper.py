"""
scrapers/wellfound_scraper.py — Wellfound (AngelList) startup job scraper
Focuses on AI/ML/SWE roles at startups. Uses Playwright.
"""
import asyncio
import random
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

WELLFOUND_SEARCH_URLS = [
    "https://wellfound.com/jobs?role=software-engineer&location=remote&years_of_experience=0&remote=true",
    "https://wellfound.com/jobs?role=machine-learning-engineer&location=remote&years_of_experience=0&remote=true",
    "https://wellfound.com/jobs?role=data-scientist&location=remote&years_of_experience=0&remote=true",
    "https://wellfound.com/jobs?role=python-developer&location=remote&years_of_experience=0&remote=true",
]


async def scrape_wellfound_async(max_jobs: int = 20) -> List[Dict]:
    """Scrape Wellfound for startup jobs. No login needed for basic listings."""
    try:
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth
    except ImportError:
        logger.error("playwright not installed")
        return []

    jobs = []
    seen_urls = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)

        for search_url in WELLFOUND_SEARCH_URLS:
            if len(jobs) >= max_jobs:
                break

            try:
                logger.info(f"Wellfound: Scraping {search_url}")
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(random.uniform(3, 5))

                # Scroll to load more
                for _ in range(3):
                    await page.keyboard.press("End")
                    await asyncio.sleep(2)

                # Get all job listing divs
                cards = await page.query_selector_all(
                    "div[data-test='StartupResult'], div.styles_component__Ey28k"
                )

                for card in cards[:10]:
                    try:
                        job = await _extract_wellfound_job(card, page)
                        if job and job["url"] not in seen_urls:
                            seen_urls.add(job["url"])
                            jobs.append(job)
                    except Exception as e:
                        logger.debug(f"Wellfound card error: {e}")

            except Exception as e:
                logger.error(f"Wellfound error: {e}")

            await asyncio.sleep(random.uniform(3, 5))

        await browser.close()

    logger.info(f"Wellfound: Found {len(jobs)} jobs")
    return jobs


async def _extract_wellfound_job(card, page) -> Dict:
    """Extract job from a Wellfound job card."""
    try:
        # Look for job title and company
        title_el = await card.query_selector("a[href*='/jobs/']")
        company_el = await card.query_selector("a[href*='/company/']")
        location_el = await card.query_selector("span[class*='location']")

        title = (await title_el.inner_text()).strip() if title_el else ""
        company = (await company_el.inner_text()).strip() if company_el else ""
        location = (await location_el.inner_text()).strip() if location_el else "Remote"
        href = await title_el.get_attribute("href") if title_el else ""

        if not title or not href:
            return None

        url = href if href.startswith("http") else f"https://wellfound.com{href}"

        return {
            "title": title,
            "company": company,
            "location": location,
            "url": url,
            "description": f"{title} at {company}. Location: {location}",
            "portal": "wellfound",
            "is_us_remote": True,
        }
    except Exception:
        return None


def scrape_wellfound(max_jobs: int = 20) -> List[Dict]:
    """Synchronous wrapper."""
    return asyncio.run(scrape_wellfound_async(max_jobs))
