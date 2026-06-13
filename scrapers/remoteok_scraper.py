"""
scrapers/remoteok_scraper.py — RemoteOK free JSON API scraper
No authentication needed. Returns remote jobs with salary info.
"""
import requests
import logging
import time
from typing import List, Dict

logger = logging.getLogger(__name__)

REMOTEOK_API_URL = "https://remoteok.com/api"

TARGET_TAGS = [
    "python", "ai", "machine-learning", "ml", "nlp", "deep-learning",
    "data-science", "backend", "javascript", "react", "node", "golang",
    "cpp", "c++", "java", "software-engineer", "devops", "fullstack",
    "junior", "entry-level"
]

def scrape_remoteok(max_jobs: int = 50) -> List[Dict]:
    """
    Scrape RemoteOK for relevant remote tech jobs.
    RemoteOK has a free public JSON API at https://remoteok.com/api
    """
    jobs = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    try:
        logger.info("Scraping RemoteOK API...")
        time.sleep(2)  # Be respectful - they ask for a delay
        
        resp = requests.get(REMOTEOK_API_URL, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # First item is a legal notice object, skip it
        listings = [item for item in data if isinstance(item, dict) and "id" in item]

        for item in listings:
            tags = [t.lower() for t in item.get("tags", [])]

            # Check if job matches our target areas
            is_relevant = any(
                target in " ".join(tags) or target in item.get("position", "").lower()
                for target in ["python", "ai", "ml", "machine learning", "c++",
                               "software", "engineer", "developer", "data"]
            )

            if not is_relevant:
                continue

            # Check for fresher-friendly (no strict experience filter on RemoteOK)
            description = item.get("description", "")
            
            # Build job object
            job = {
                "title": item.get("position", ""),
                "company": item.get("company", ""),
                "location": "Remote",
                "url": item.get("url", f"https://remoteok.com/l/{item.get('id', '')}"),
                "description": _clean_html(description),
                "portal": "remoteok",
                "tags": tags,
                "salary": item.get("salary_min", ""),
                "date_posted": item.get("date", ""),
                "company_logo": item.get("company_logo", ""),
                "apply_url": item.get("apply_url", item.get("url", "")),
                "is_us_remote": True,
            }

            if job["title"] and job["url"]:
                jobs.append(job)

            if len(jobs) >= max_jobs:
                break

        logger.info(f"RemoteOK: Found {len(jobs)} relevant jobs")

    except requests.RequestException as e:
        logger.error(f"RemoteOK scraping failed: {e}")
    except Exception as e:
        logger.error(f"RemoteOK unexpected error: {e}")

    return jobs


def _clean_html(text: str) -> str:
    """Remove basic HTML tags from text."""
    import re
    clean = re.compile('<.*?>')
    return re.sub(clean, ' ', text).strip()
