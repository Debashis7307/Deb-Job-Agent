"""
config.py — Central configuration loader for the Job Application Agent
Loads from .env and data/user_profile.json
"""
import json
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ─── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
DB_DIR = BASE_DIR / "database"
TEMPLATES_DIR = BASE_DIR / "templates"

# Ensure directories exist
for d in [DATA_DIR, LOGS_DIR, DB_DIR, TEMPLATES_DIR]:
    d.mkdir(exist_ok=True)

# ─── Load User Profile ───────────────────────────────────────────────────────
with open(DATA_DIR / "user_profile.json", "r", encoding="utf-8") as f:
    USER_PROFILE = json.load(f)

# ─── Gemini AI Config ────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

if not GEMINI_API_KEY:
    raise ValueError("❌ GEMINI_API_KEY not set in .env file!")

# ─── Gmail Config ────────────────────────────────────────────────────────────
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")       # Job-specific email (sends cold emails)
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
PERSONAL_EMAIL = os.getenv("PERSONAL_EMAIL", GMAIL_ADDRESS)  # Personal email (receives summary)

if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
    raise ValueError("❌ Gmail credentials not set in .env file!")

# ─── mem0 Config ─────────────────────────────────────────────────────────────
MEM0_API_KEY = os.getenv("MEM0_API_KEY", "")
MEM0_USER_ID = os.getenv("MEM0_USER_ID", "job_agent_user_001")
USE_MEM0 = bool(MEM0_API_KEY)

# ─── B2B Email Search & Verification APIs ────────────────────────────────────
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY", "")
SNOV_CLIENT_ID = os.getenv("SNOV_CLIENT_ID", "")
SNOV_CLIENT_SECRET = os.getenv("SNOV_CLIENT_SECRET", "")

# ─── Tavily Real-Time Search API ───────────────────────────────────
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
USE_TAVILY = bool(TAVILY_API_KEY)
# Tavily free tier: ~1000 searches/month = ~33/day safely.
# Using 30/day to leave buffer for occasional extra test runs.
# scrape_node uses max 10 (reserves 5 for email discovery, 15 slack).
TAVILY_DAILY_LIMIT = int(os.getenv("TAVILY_DAILY_LIMIT", "30"))

# ─── LinkedIn Config ─────────────────────────────────────────────────────────
LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")
USE_LINKEDIN = bool(LINKEDIN_EMAIL and LINKEDIN_PASSWORD)

# ─── Naukri Config ───────────────────────────────────────────────────────────
NAUKRI_EMAIL = os.getenv("NAUKRI_EMAIL", "")
NAUKRI_PASSWORD = os.getenv("NAUKRI_PASSWORD", "")
USE_NAUKRI = bool(NAUKRI_EMAIL and NAUKRI_PASSWORD)

# ─── Internshala Config ──────────────────────────────────────────────────────
INTERNSHALA_EMAIL = os.getenv("INTERNSHALA_EMAIL", "")
INTERNSHALA_PASSWORD = os.getenv("INTERNSHALA_PASSWORD", "")
USE_INTERNSHALA_LOGIN = bool(INTERNSHALA_EMAIL and INTERNSHALA_PASSWORD)

# ─── Web Dashboard ───────────────────────────────────────────────────────────
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "5000"))
DASHBOARD_SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY", "change_me_secret")

# ─── Agent Settings ──────────────────────────────────────────────────────────
DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "true"
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "False").lower() == "true"
MAX_APPLY_PER_DAY = int(os.getenv("MAX_APPLY_PER_DAY", "30"))
MAX_EMAIL_PER_DAY = int(os.getenv("MAX_EMAIL_PER_DAY", "25"))
SCHEDULE_HOUR = int(os.getenv("SCHEDULE_HOUR", "9"))
SCHEDULE_MINUTE = int(os.getenv("SCHEDULE_MINUTE", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")

# ─── Database ─────────────────────────────────────────────────────────────────
DB_PATH = str(DB_DIR / "tracker.db")

# ─── Gemini Rate Limiting ─────────────────────────────────────────────────────
# Free tier: 15 RPM, 1500 RPD
# We batch calls to stay well under limits
GEMINI_MAX_RPM = 12          # Conservative: leave buffer below 15
GEMINI_DELAY_BETWEEN_CALLS = 5  # Seconds between LLM calls
GEMINI_BATCH_SIZE = 10       # Score this many jobs per single LLM call
EMAIL_BATCH_SIZE = 5         # Generate this many emails per single LLM call

# ─── User shortcuts for convenience ──────────────────────────────────────────
USER_NAME = USER_PROFILE["personal"]["name"]
USER_EMAIL = USER_PROFILE["personal"]["email"]
USER_PHONE = USER_PROFILE["personal"]["phone"]
USER_LINKEDIN = USER_PROFILE["personal"]["linkedin_url"]
USER_GITHUB = USER_PROFILE["personal"]["github_url"]
USER_PORTFOLIO = USER_PROFILE["personal"]["portfolio_url"]
RESUME_PATH = str(BASE_DIR / USER_PROFILE["personal"]["resume_path"])
RESUME_PDF_PATH = RESUME_PATH  # Alias — both names work
TARGET_ROLES = USER_PROFILE["target_roles"]
TARGET_KEYWORDS = USER_PROFILE["target_keywords"]
EXCLUDE_KEYWORDS = USER_PROFILE["exclude_keywords"]
SKILLS = USER_PROFILE["skills"]
PROJECTS = USER_PROFILE["projects"]
USER_PROFILE_PATH = str(DATA_DIR / "user_profile.json")  # Explicit path for pdf_outreach_node
