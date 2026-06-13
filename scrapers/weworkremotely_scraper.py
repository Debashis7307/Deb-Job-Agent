"""
scrapers/weworkremotely_scraper.py — We Work Remotely (WWR) job scraper
Uses WWR's free programming category RSS feed.
"""
import logging
import requests
from typing import List, Dict
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

RSS_URL = "https://weworkremotely.com/categories/remote-programming-jobs.rss"


def scrape_weworkremotely(max_jobs: int = 30) -> List[Dict]:
    """Scrape We Work Remotely programming jobs using their public RSS feed."""
    jobs = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        logger.info("WWR: Fetching jobs from RSS feed...")
        resp = requests.get(RSS_URL, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"WWR: Failed to fetch feed with status {resp.status_code}")
            return []

        # Parse as XML
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")

        for item in items[:max_jobs]:
            try:
                title_text = item.find("title").text if item.find("title") else ""
                # Title format is usually "Company: Job Title"
                company = "Unknown"
                title = title_text
                if ":" in title_text:
                    parts = title_text.split(":", 1)
                    company = parts[0].strip()
                    title = parts[1].strip()

                url = item.find("link").text if item.find("link") else ""
                description = item.find("description").text if item.find("description") else ""

                if not url or not title:
                    continue

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": "Remote",
                    "url": url,
                    "description": description[:1500],
                    "portal": "weworkremotely",
                    "is_easy_apply": False,
                    "is_us_remote": True,
                })
            except Exception as e:
                logger.debug(f"WWR: Error parsing item: {e}")

    except Exception as e:
        logger.error(f"WWR: Scraper failed: {e}")

    logger.info(f"WWR: Found {len(jobs)} jobs")
    return jobs
