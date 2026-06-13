"""Quick Tavily test — run from project root. Requires TAVILY_API_KEY in .env"""
import sys
import os
sys.path.insert(0, ".")
# Load key from .env — do NOT hardcode API keys here

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Load config from .env
from dotenv import load_dotenv
load_dotenv()
import config as cfg

print(f"\n[TAVILY] API key set: {bool(cfg.TAVILY_API_KEY)}")
print(f"[TAVILY] USE_TAVILY: {cfg.USE_TAVILY}")
print(f"[TAVILY] Daily limit: {cfg.TAVILY_DAILY_LIMIT}")

from tools.tavily_search import search_startup_jobs, search_free_job_portals, get_today_tavily_count

print(f"\n[TAVILY] Searches used today so far: {get_today_tavily_count()}")

print("\n[TEST 1] Searching startup job boards...")
jobs = search_startup_jobs("python AI engineer fresher")
print(f"  -> Found {len(jobs)} startup job leads")
for j in jobs[:3]:
    print(f"     - {j['title']} | {j['url'][:70]}")

print("\n[TEST 2] Searching free job portals (Remotive, Himalayas etc.)...")
portal_jobs = search_free_job_portals(max_portals=2)
print(f"  -> Found {len(portal_jobs)} jobs from free portals")
for j in portal_jobs[:3]:
    print(f"     - {j['title']} @ {j['company']} | {j['url'][:70]}")

print(f"\n[TAVILY] Total searches used today: {get_today_tavily_count()}/{cfg.TAVILY_DAILY_LIMIT}")
print("\n[DONE] Tavily test complete!")
