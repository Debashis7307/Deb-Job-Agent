"""
scrapers/internshala_scraper.py — Internshala internship & job scraper
Uses requests + BeautifulSoup. No login needed for browsing.
"""
import requests
import time
import logging
import random
from typing import List, Dict
from bs4 import BeautifulSoup
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

BASE_URL = "https://internshala.com"

# Search URLs for different categories
SEARCH_URLS = [
    "/internships/python-internship",
    "/internships/machine-learning-internship",
    "/internships/artificial-intelligence-internship",
    "/internships/web-development-internship",
    "/internships/computer-science-internship",
    "/internships/data-science-internship",
    "/jobs/fresher-jobs",
    "/jobs/python-jobs",
    "/jobs/software-development-jobs",
    "/jobs/ai-ml-jobs",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}


def scrape_internshala(max_jobs: int = 40) -> List[Dict]:
    """
    Scrape Internshala for freshers jobs and internships.
    """
    all_jobs = []
    seen_urls = set()
    session = requests.Session()
    session.headers.update(HEADERS)

    for search_path in SEARCH_URLS:
        if len(all_jobs) >= max_jobs:
            break

        url = BASE_URL + search_path
        try:
            logger.info(f"Internshala: Scraping {url}")
            time.sleep(random.uniform(2, 4))  # Human-like delay

            resp = session.get(url, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"Internshala: Status {resp.status_code} for {url}")
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            jobs = _parse_internshala_listings(soup, search_path)

            for job in jobs:
                if job["url"] not in seen_urls:
                    seen_urls.add(job["url"])
                    all_jobs.append(job)

        except Exception as e:
            logger.error(f"Internshala error for {url}: {e}")

    logger.info(f"Internshala: Total {len(all_jobs)} jobs found")
    return all_jobs[:max_jobs]


def _parse_internshala_listings(soup: BeautifulSoup, search_path: str) -> List[Dict]:
    """Parse job/internship cards from Internshala listing page."""
    jobs = []
    is_job = "/jobs/" in search_path

    # Internshala uses .internship_meta or .job_internship_tab for cards
    cards = soup.find_all("div", class_=lambda c: c and (
        "internship_meta" in c or "individual_internship" in c
    ))

    for card in cards:
        try:
            # Job title
            title_tag = card.find("h3", class_="job-internship-name") or \
                        card.find("a", class_="job-title-href")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)

            # Company
            company_tag = card.find("h4", class_="company-name") or \
                          card.find("p", class_="company-name")
            company = company_tag.get_text(strip=True) if company_tag else "Unknown"

            # URL
            link = card.find("a", class_="job-title-href") or \
                   card.find("a", attrs={"href": True})
            href = link["href"] if link else ""
            if not href:
                continue
            job_url = href if href.startswith("http") else urljoin(BASE_URL, href)

            # Location/Stipend
            location_tag = card.find("p", class_="locations")
            location = location_tag.get_text(strip=True) if location_tag else "India"

            stipend_tag = card.find("span", class_="stipend")
            stipend = stipend_tag.get_text(strip=True) if stipend_tag else ""

            # Duration (for internships)
            duration_tag = card.find("span", class_="item_body")
            duration = duration_tag.get_text(strip=True) if duration_tag else ""

            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "url": job_url,
                "description": f"{title} at {company}. Stipend: {stipend}. Duration: {duration}",
                "portal": "internshala",
                "stipend": stipend,
                "is_internship": not is_job,
                "is_us_remote": False,
            })

        except Exception as e:
            logger.debug(f"Internshala card parse error: {e}")

    return jobs


def get_job_details(job_url: str) -> str:
    """Fetch full job description from individual job page."""
    try:
        time.sleep(random.uniform(1, 2))
        resp = requests.get(job_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")

        # Try to find the job description section
        desc_div = soup.find("div", class_="about_company_text_section") or \
                   soup.find("div", id="about_the_company") or \
                   soup.find("div", class_="internship-other-details-container")

        if desc_div:
            return desc_div.get_text(separator=" ", strip=True)[:1500]
    except Exception:
        pass
    return ""
