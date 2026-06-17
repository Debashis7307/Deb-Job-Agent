"""
scrapers/linkedin_scraper.py -- LinkedIn job scraper using Playwright stealth
PERSONAL USE ONLY -- respects rate limits and human-like delays.
"""
import asyncio
import random
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

LINKEDIN_SEARCH_CONFIGS = [
    {"keywords": "python developer fresher", "location": "India", "f_TPR": "r86400", "f_E": "1"},
    {"keywords": "software engineer fresher entry level", "location": "India", "f_TPR": "r86400", "f_E": "1"},
    {"keywords": "machine learning engineer fresher", "location": "India", "f_TPR": "r86400", "f_E": "1"},
    {"keywords": "AI engineer generative AI fresher", "location": "India", "f_TPR": "r86400", "f_E": "1"},
    {"keywords": "software developer python AI remote", "location": "United States", "f_TPR": "r86400", "f_E": "1", "f_WT": "2"},
    {"keywords": "junior python developer remote", "location": "United States", "f_TPR": "r86400", "f_E": "1", "f_WT": "2"},
]


async def scrape_linkedin_async(
    email: str, password: str, max_jobs: int = 30, dry_run: bool = True
) -> List[Dict]:
    """Scrape LinkedIn jobs using Playwright with stealth mode."""
    try:
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth
    except ImportError:
        logger.error("playwright and playwright-stealth not installed")
        return []

    jobs = []
    seen_urls = set()

    async with async_playwright() as p:
        import config as cfg
        browser = await p.chromium.launch(
            headless=cfg.BROWSER_HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
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

        # Login
        if not dry_run:
            try:
                logger.info("LinkedIn: Logging in...")
                await page.goto(
                    "https://www.linkedin.com/login",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                await asyncio.sleep(random.uniform(3, 5))

                # Try each username selector individually
                filled_username = False
                for sel in [
                    "#username",
                    "input[name='session_key']",
                    "input[autocomplete='username']",
                    "input[type='email']",
                ]:
                    try:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            await el.wait_for(state="visible", timeout=5000)
                            await el.fill(email)
                            filled_username = True
                            break
                    except Exception:
                        continue

                if not filled_username:
                    raise RuntimeError("Could not find username/email field on LinkedIn login page")

                await asyncio.sleep(random.uniform(0.8, 1.5))

                # Try each password selector individually
                filled_password = False
                for sel in [
                    "#password",
                    "input[name='session_password']",
                    "input[autocomplete='current-password']",
                    "input[type='password']",
                ]:
                    try:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            await el.wait_for(state="visible", timeout=5000)
                            await el.fill(password)
                            filled_password = True
                            break
                    except Exception:
                        continue

                if not filled_password:
                    raise RuntimeError("Could not find password field on LinkedIn login page")

                await asyncio.sleep(random.uniform(0.5, 1.2))

                submit_selector = (
                    "button[type='submit'], "
                    "button.btn__primary--large, "
                    "button[aria-label='Sign in'], "
                    "button[data-litms-control-urn='login-submit']"
                )
                await page.locator(submit_selector).first.click()
                await asyncio.sleep(random.uniform(6, 9))

                current_url = page.url
                if any(part in current_url for part in ["/feed", "/mynetwork", "/jobs"]):
                    logger.info("LinkedIn: Login successful")
                elif "checkpoint" in current_url:
                    logger.warning("LinkedIn: CAPTCHA checkpoint detected. Continuing with public search...")
                elif "login" in current_url:
                    logger.warning("LinkedIn: Still on login page. Continuing with public search...")
                else:
                    logger.info("LinkedIn: Redirected after login -- assuming logged in.")

            except Exception as e:
                logger.error(f"LinkedIn login failed: {e}. Proceeding with public search...")

        # Scrape job listings
        for cfg_item in LINKEDIN_SEARCH_CONFIGS:
            if len(jobs) >= max_jobs:
                break

            search_url = _build_linkedin_url(cfg_item)
            try:
                logger.info(f"LinkedIn: Searching '{cfg_item['keywords']}'")
                await page.goto(search_url, wait_until="domcontentloaded")
                await asyncio.sleep(random.uniform(3, 5))

                for _ in range(3):
                    await page.keyboard.press("End")
                    await asyncio.sleep(random.uniform(1, 2))

                job_cards = await page.query_selector_all(
                    "div.job-search-card, li.jobs-search-results__list-item"
                )

                for card in job_cards[:15]:
                    try:
                        job = await _extract_linkedin_job(card, page)
                        if job and job["url"] not in seen_urls:
                            seen_urls.add(job["url"])
                            jobs.append(job)
                    except Exception as e:
                        logger.debug(f"LinkedIn card error: {e}")

            except Exception as e:
                logger.error(f"LinkedIn search error: {e}")

            await asyncio.sleep(random.uniform(4, 7))

        await browser.close()

    logger.info(f"LinkedIn: Found {len(jobs)} jobs")
    return jobs


async def _extract_linkedin_job(card, page) -> Dict:
    """Extract job details from a LinkedIn job card."""
    title_el = await card.query_selector("h3.base-search-card__title, a.job-card-list__title")
    company_el = await card.query_selector("h4.base-search-card__subtitle, a.job-card-container__company-name")
    location_el = await card.query_selector("span.job-search-card__location")
    link_el = await card.query_selector("a.base-card__full-link, a.job-card-list__title")

    title = await title_el.inner_text() if title_el else ""
    company = await company_el.inner_text() if company_el else ""
    location = await location_el.inner_text() if location_el else ""
    href = await link_el.get_attribute("href") if link_el else ""

    if not title or not href:
        return None

    url = href.split("?")[0] if href else ""

    return {
        "title": title.strip(),
        "company": company.strip(),
        "location": location.strip(),
        "url": url,
        "description": title.strip() + " at " + company.strip(),
        "portal": "linkedin",
        "is_easy_apply": False,
        "is_us_remote": "United States" in location or "Remote" in location,
    }


def _build_linkedin_url(config: dict) -> str:
    """Build LinkedIn job search URL from config dict."""
    from urllib.parse import urlencode
    base = "https://www.linkedin.com/jobs/search/?"
    params = {
        "keywords": config.get("keywords", ""),
        "location": config.get("location", "India"),
        "f_TPR": config.get("f_TPR", "r86400"),
    }
    if "f_E" in config:
        params["f_E"] = config["f_E"]
    if "f_WT" in config:
        params["f_WT"] = config["f_WT"]
    return base + urlencode(params)


def scrape_linkedin(email: str, password: str, max_jobs: int = 30, dry_run: bool = True) -> List[Dict]:
    """Synchronous wrapper for the async LinkedIn scraper."""
    return asyncio.run(scrape_linkedin_async(email, password, max_jobs, dry_run))
