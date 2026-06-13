"""
tools/email_finder.py — Find HR recruiter emails for free
Strategy (in order):
  1. Extract domain directly from job_url (most reliable!)
  2. Smart company-name → domain guessing
  3. Scrape company website /contact, /about pages
  4. Common HR email patterns: hr@, careers@, recruitment@, hiring@
  5. DuckDuckGo search fallback
"""
import re
import time
import logging
import random
import requests
from typing import Optional, List, Dict
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from email_validator import validate_email, EmailNotValidError
import config as cfg

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')

CONTACT_PAGE_PATHS = [
    "/contact", "/contact-us", "/about", "/about-us",
    "/team", "/careers", "/jobs", "/hire", "/recruitment", "/people"
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Skip these non-company domains when extracting from job URLs
JOB_PORTAL_DOMAINS = {
    "internshala.com", "linkedin.com", "naukri.com", "remoteok.com",
    "remoteok.io", "wellfound.com", "angel.co", "indeed.com",
    "glassdoor.com", "monster.com", "shine.com", "timesjobs.com",
    "foundit.in", "apna.co", "freshersworld.com",
}

HR_KEYWORDS = [
    "hr", "recruit", "hiring", "talent", "people", "careers",
    "jobs", "apply", "human.resource", "humanresource"
]

# Domains that are known IT/tech companies — we can guess their email patterns
KNOWN_TECH_COMPANIES = {
    "honeywell": "honeywell.com",
    "bored panda": "boredpanda.com",
    "kennedy krieger": "kennedykrieger.org",
}


SNOV_TOKEN_CACHE = {"token": "", "expires_at": 0}

def get_snov_token() -> Optional[str]:
    """Get or refresh Snov.io OAuth access token."""
    if not cfg.SNOV_CLIENT_ID or not cfg.SNOV_CLIENT_SECRET:
        return None
        
    now = time.time()
    if SNOV_TOKEN_CACHE["token"] and SNOV_TOKEN_CACHE["expires_at"] > now + 60:
        return SNOV_TOKEN_CACHE["token"]
        
    try:
        url = "https://api.snov.io/v1/oauth/access_token"
        data = {
            "grant_type": "client_credentials",
            "client_id": cfg.SNOV_CLIENT_ID,
            "client_secret": cfg.SNOV_CLIENT_SECRET
        }
        resp = requests.post(url, data=data, timeout=10)
        if resp.status_code == 200:
            res_data = resp.json()
            token = res_data.get("access_token")
            expires_in = res_data.get("expires_in", 3600)
            if token:
                SNOV_TOKEN_CACHE["token"] = token
                SNOV_TOKEN_CACHE["expires_at"] = now + expires_in
                logger.info("Successfully refreshed Snov.io API access token.")
                return token
    except Exception as e:
        logger.error(f"Snov.io oauth failed: {e}")
    return None


def snov_domain_search(domain: str) -> List[str]:
    """Scrape emails linked to a domain using Snov.io API."""
    token = get_snov_token()
    if not token:
        return []
        
    try:
        url_start = "https://api.snov.io/v2/domain-search/domain-emails/start"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        resp_start = requests.post(url_start, headers=headers, json={"domain": domain}, timeout=10)
        if resp_start.status_code not in (200, 202):
            logger.warning(f"Snov.io domain search start failed with status {resp_start.status_code}")
            return []
            
        task_hash = resp_start.json().get("meta", {}).get("task_hash")
        if not task_hash:
            return []
            
        url_result = f"https://api.snov.io/v2/domain-search/domain-emails/result/{task_hash}"
        for attempt in range(3):
            time.sleep(3)
            resp_result = requests.get(url_result, headers=headers, timeout=10)
            if resp_result.status_code == 200:
                res_data = resp_result.json()
                if res_data.get("status") == "completed":
                    emails = [item.get("email") for item in res_data.get("data", []) if item.get("email")]
                    logger.info(f"Snov.io found {len(emails)} emails for {domain}")
                    return emails
            else:
                break
    except Exception as e:
        logger.error(f"Snov.io domain search failed for {domain}: {e}")
    return []


def verify_email_with_snov(email: str) -> Optional[bool]:
    """
    Verify email address validity using Snov.io verifier API.
    Returns True if valid/catchall, False if invalid, None if check failed.
    """
    token = get_snov_token()
    if not token:
        return None
        
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        url_add = "https://api.snov.io/v1/add-emails-to-verification"
        resp_add = requests.post(url_add, headers=headers, json={"emails": [email]}, timeout=10)
        if resp_add.status_code != 200:
            return None
            
        time.sleep(3)
        
        url_status = "https://api.snov.io/v1/get-emails-verification-status"
        resp_status = requests.post(url_status, headers=headers, json={"emails": [email]}, timeout=10)
        if resp_status.status_code == 200:
            res_data = resp_status.json()
            email_info = res_data.get(email, {})
            status = email_info.get("status", {}).get("identifier")
            
            if status == "complete":
                data = email_info.get("data", {})
                smtp_status = data.get("smtpStatus")
                is_valid = data.get("isValidFormat", True)
                
                if smtp_status == "invalid" or not is_valid:
                    logger.warning(f"Snov.io verified {email} is INVALID (SMTP: {smtp_status})")
                    return False
                logger.info(f"Snov.io verified {email} is deliverable (SMTP: {smtp_status})")
                return True
    except Exception as e:
        logger.error(f"Snov.io email verification failed for {email}: {e}")
    return None

def get_today_apollo_count() -> int:
    """Count how many Apollo enrichments we have done today."""
    try:
        import sqlite3
        with sqlite3.connect(cfg.DB_PATH) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM hr_contacts WHERE source = 'apollo_enrichment' AND date(created_at, 'localtime') = date('now', 'localtime')"
            ).fetchone()
            return row[0] if row else 0
    except Exception as e:
        logger.error(f"Error checking Apollo daily count: {e}")
        return 0


# Module-level flag: set True when Apollo returns 422 (no credits left)
_APOLLO_CREDITS_EXHAUSTED = False


def apollo_search_and_enrich(company_name: str, domain: str) -> Optional[str]:
    """
    Two-step Apollo CRM retrieval using free endpoints:
    1. Search globally for the organization using /v1/organizations/search to get its ID.
    2. Search for saved contacts at that organization using /v1/contacts/search.
    """
    global _APOLLO_CREDITS_EXHAUSTED
    if not cfg.APOLLO_API_KEY:
        return None
    if _APOLLO_CREDITS_EXHAUSTED:
        return None  # Skip silently — credits confirmed exhausted this session

    # Check daily limit of 2 successful email enrichments per day
    today_count = get_today_apollo_count()
    if today_count >= 2:
        logger.info(f"Apollo daily limit reached ({today_count}/2). Skipping Apollo.")
        return None

    try:
        headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": cfg.APOLLO_API_KEY
        }

        # Step 1: Search for organization to get org_id
        url_org = "https://api.apollo.io/v1/organizations/search"
        payload_org = {
            "q_organization_domains_list": [domain],
            "per_page": 1
        }
        
        org_id = None
        resp_org = requests.post(url_org, json=payload_org, headers=headers, timeout=10)
        if resp_org.status_code == 200:
            orgs_data = resp_org.json()
            orgs = orgs_data.get("organizations", [])
            if orgs:
                org_id = orgs[0].get("id")
                logger.info(f"Apollo: Found global organization ID {org_id} for domain {domain}")
        elif resp_org.status_code == 422:
            _APOLLO_CREDITS_EXHAUSTED = True  # Mark as exhausted — skip all further Apollo calls
            logger.warning("Apollo: Credits exhausted (422). Disabling Apollo for this session.")
            return None
        else:
            logger.warning(f"Apollo organization search failed with status {resp_org.status_code}: {resp_org.text[:100]}")

        # Step 2: Search contacts in CRM
        url_contacts = "https://api.apollo.io/v1/contacts/search"
        
        contacts = []
        if org_id:
            payload_contacts = {
                "organization_ids": [org_id],
                "per_page": 10
            }
            resp_contacts = requests.post(url_contacts, json=payload_contacts, headers=headers, timeout=10)
            if resp_contacts.status_code == 200:
                contacts = resp_contacts.json().get("contacts", [])
        
        # Fallback search by keyword/domain
        if not contacts:
            payload_fallback = {
                "q_keywords": f"{company_name} OR {domain}",
                "per_page": 10
            }
            resp_fallback = requests.post(url_contacts, json=payload_fallback, headers=headers, timeout=10)
            if resp_fallback.status_code == 200:
                contacts = resp_fallback.json().get("contacts", [])

        # Process found contacts
        for contact in contacts:
            email = contact.get("email")
            if email:
                # Check if it matches HR roles or general deliverability
                if verify_email_deliverability(email):
                    logger.info(f"Apollo: Found saved contact email in CRM: {email}")
                    return email

    except Exception as e:
        logger.error(f"Apollo CRM search failed: {e}")
    return None



def verify_email_deliverability(email_address: str) -> bool:
    """
    Verify if the email syntax is correct, domain resolves, and domain has active MX records.
    Returns False on any failure (transient or permanent) to avoid high bounce rates.
    """
    import socket
    try:
        # 1. Syntax check
        valid = validate_email(email_address, check_deliverability=False)
        # .normalized is the correct attribute in email-validator 2.x (.email is deprecated)
        email_clean = getattr(valid, "normalized", None) or getattr(valid, "email", email_address)
        domain = email_clean.split("@")[-1].strip().lower()
        
        # 2. Fast built-in host resolution (uses native OS DNS)
        try:
            socket.gethostbyname(domain)
        except (socket.gaierror, socket.herror) as se:
            logger.warning(f"❌ Domain resolution failed for {domain} (Host not found): {se}")
            return False
            
        # 3. Deep Snov.io Mailbox Verification (if credentials exist)
        snov_result = verify_email_with_snov(email_clean)
        if snov_result is False:
            return False
        elif snov_result is True:
            return True
            
        # 4. Fallback: MX record lookup using dnspython
        try:
            import dns.resolver
            resolver = dns.resolver.Resolver()
            resolver.timeout = 3.0
            resolver.lifetime = 3.0
            
            answers = resolver.resolve(domain, 'MX')
            if len(answers) > 0:
                logger.info(f"✅ Verified MX records for {domain}")
                return True
        except Exception as mx_err:
            logger.warning(f"❌ MX record lookup failed for {domain}: {mx_err}")
            return False

    except EmailNotValidError as e:
        logger.debug(f"Syntax validation failed for {email_address}: {e}")
        return False
    except Exception as e:
        logger.error(f"Deliverability check error for {email_address}: {e}")
        return False

    return False


def extract_domain_from_url(job_url: str) -> Optional[str]:
    """Extract the company domain directly from the job listing URL."""
    try:
        parsed = urlparse(job_url)
        netloc = parsed.netloc.lower().replace("www.", "")
        if netloc and not any(portal in netloc for portal in JOB_PORTAL_DOMAINS):
            return netloc
    except Exception:
        pass
    return None


def company_name_to_domain_guess(company_name: str) -> List[str]:
    """Guess likely domains from company name (no network call needed)."""
    name = company_name.lower().strip()

    # Check known companies first
    for keyword, domain in KNOWN_TECH_COMPANIES.items():
        if keyword in name:
            return [domain]

    # Strip parenthetical suffixes e.g. "RDash (YC W22)" → "rdash"
    name = re.sub(r'\s*[\(\[].*?[\)\]]', '', name).strip()

    # Strip everything after first comma (company descriptions)
    if ',' in name:
        name = name.split(',')[0].strip()

    # Strip regional/geographic qualifiers that make domain slugs too long
    # e.g. "Stefanini North America and APAC" → "stefanini"
    REGIONAL_PATTERNS = [
        r'\s+north\s+america.*', r'\s+and\s+apac.*', r'\s+apac.*',
        r'\s+south\s+asia.*', r'\s+asia\s+pacific.*',
        r'\s+india\b', r'\s+global\b', r'\s+worldwide\b',
        r'\s+emea.*', r'\s+latam.*',
    ]
    for pat in REGIONAL_PATTERNS:
        name = re.sub(pat, '', name, flags=re.IGNORECASE).strip()

    # Clean up company name → slug
    # Remove common suffixes
    for suffix in [" private limited", " pvt ltd", " pvt. ltd.", " llp", " llc",
                   " inc", " ltd", " limited", " technologies", " solutions",
                   " consultancy", " enterprises", " foundation", " institute",
                   " official page", " india", " global", " services"]:
        name = name.replace(suffix, "")

    # Replace spaces & special chars with nothing or hyphen
    slug_nospace = re.sub(r"[^a-z0-9]", "", name)
    slug_hyphen = re.sub(r"[^a-z0-9]+", "-", name).strip("-")

    candidates = []
    for tld in [".com", ".in", ".io", ".co.in", ".org"]:
        if slug_nospace:
            candidates.append(slug_nospace + tld)
        if slug_hyphen and slug_hyphen != slug_nospace:
            candidates.append(slug_hyphen + tld)

    return candidates[:6]


def get_company_domain(company_name: str, job_url: str = "") -> Optional[str]:
    """
    Find company domain using multiple strategies.
    Priority: job_url domain > known company > DuckDuckGo > name guess
    """
    # 1. Extract from job URL directly (fastest, most reliable)
    if job_url:
        domain = extract_domain_from_url(job_url)
        if domain:
            logger.info(f"Domain from URL for {company_name}: {domain}")
            return domain

    # 2. Known companies
    name_lower = company_name.lower()
    for keyword, domain in KNOWN_TECH_COMPANIES.items():
        if keyword in name_lower:
            logger.info(f"Domain from known list for {company_name}: {domain}")
            return domain

    # 3. DuckDuckGo search (with short timeout, don't block)
    try:
        url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(company_name + ' official website')}"
        resp = requests.get(url, headers=HEADERS, timeout=8)

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            # Try result__url class (DDG HTML format)
            links = soup.find_all("a", class_="result__url")
            if not links:
                # Try href links in results
                links = soup.find_all("a", href=True)

            for link in links[:8]:
                href = link.get("href", "") or link.get_text(strip=True)
                try:
                    parsed = urlparse(href if href.startswith("http") else f"https://{href}")
                    domain = parsed.netloc.lower().replace("www.", "")
                    if domain and len(domain) > 3 and not any(
                        skip in domain for skip in [
                            "linkedin", "indeed", "naukri", "glassdoor",
                            "google", "facebook", "wikipedia", "twitter",
                            "youtube", "duckduckgo", "bing"
                        ]
                    ):
                        logger.info(f"Domain from DDG for {company_name}: {domain}")
                        return domain
                except Exception:
                    continue
    except Exception as e:
        logger.debug(f"DuckDuckGo failed for {company_name}: {e}")

    return None


def find_emails_on_website(domain: str) -> List[str]:
    """Scrape company website contact/about pages for any email address."""
    emails = []
    base_url = f"https://{domain}"

    for path in CONTACT_PAGE_PATHS[:4]:  # Only check first 4 paths to save time
        try:
            resp = requests.get(base_url + path, headers=HEADERS, timeout=8)
            if resp.status_code != 200:
                continue

            found = EMAIL_REGEX.findall(resp.text)
            for email in found:
                email = email.lower()
                # Skip image/asset emails, keep real ones
                if any(bad in email for bad in [".png", ".jpg", ".gif", ".svg", "example"]):
                    continue
                emails.append(email)

            if emails:
                break  # Found emails, stop checking more pages

        except Exception:
            continue

    # Sort: prefer HR-related
    hr_emails = [e for e in emails if any(kw in e for kw in HR_KEYWORDS)]
    other_emails = [e for e in emails if e not in hr_emails and domain.split(".")[0] in e]

    return (hr_emails + other_emails)[:3]


def find_hr_email_via_duckduckgo(company_name: str, domain: str) -> List[str]:
    """
    Search DuckDuckGo for the company's founder or HR emails and parse snippets.
    e.g., query: '"company" founder email' or '"company" recruitment email'
    """
    found_emails = []
    queries = [
        f'"{company_name}" (HR OR recruiter OR hiring OR founder OR CEO) "@{domain}"',
        f'"{company_name}" (careers OR recruitment OR jobs OR contact) email'
    ]
    
    for query in queries:
        try:
            url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                # DuckDuckGo HTML format result body text
                snippets = soup.find_all("a", class_="result__snippet")
                if not snippets:
                    snippets = soup.find_all("td", class_="result-snippet")
                
                text_content = " ".join([s.get_text() for s in snippets])
                # Find all email patterns
                emails = EMAIL_REGEX.findall(text_content)
                for e in emails:
                    e = e.lower().strip()
                    if domain in e and not any(bad in e for bad in [".png", ".jpg", ".gif", "example"]):
                        found_emails.append(e)
        except Exception as e:
            logger.debug(f"DDG search for direct email failed: {e}")
            
    return list(set(found_emails))


def find_hr_email(company_name: str, job_url: str = "") -> Dict:
    """
    Main entry point: find best HR email for a company.
    Returns: {"email": str, "source": str, "confidence": str, "domain": str}
    """
    result = {"email": "", "source": "", "confidence": "low", "domain": ""}

    # ── Step 1: Get domain ────────────────────────────────────────────
    domain = get_company_domain(company_name, job_url)

    if not domain:
        # Last resort: guess domain from company name
        guesses = company_name_to_domain_guess(company_name)
        if guesses:
            domain = guesses[0]
            logger.info(f"Using guessed domain for {company_name}: {domain}")

    if not domain:
        logger.info(f"Could not determine domain for {company_name}")
        return result

    result["domain"] = domain

    # ── Step 1.5: Try Apollo Free CRM Lookup ─────────────────────────
    apollo_email = apollo_search_and_enrich(company_name, domain)
    if apollo_email:
        result["email"] = apollo_email
        result["source"] = "apollo_enrichment"
        result["confidence"] = "high"
        logger.info(f"Found saved contact email via Apollo CRM lookup for {company_name}: {apollo_email}")
        return result

    # ── Step 2: Try Snov.io Domain Search ─────────────────────────────
    snov_emails = snov_domain_search(domain)
    hr_snov = [e for e in snov_emails if any(kw in e for kw in HR_KEYWORDS)]
    other_snov = [e for e in snov_emails if e not in hr_snov]
    for email in (hr_snov + other_snov):
        if verify_email_deliverability(email):
            result["email"] = email
            result["source"] = "snov_domain_search"
            result["confidence"] = "high"
            logger.info(f"Found verified email via Snov.io domain search for {company_name}: {email}")
            return result

    # ── Step 3: Try DDG direct email search (Founder/HR) ─────────────
    direct_emails = find_hr_email_via_duckduckgo(company_name, domain)
    for email in direct_emails:
        if verify_email_deliverability(email):
            result["email"] = email
            result["source"] = "ddg_direct_search"
            result["confidence"] = "high"
            logger.info(f"Found genuine direct email via DDG search for {company_name}: {email}")
            return result

    # ── Step 3.5: Tavily real-time web search (founder/HR email) ────────
    try:
        from tools.tavily_search import search_founder_hr_email
        tavily_email = search_founder_hr_email(company_name, domain)
        if tavily_email and verify_email_deliverability(tavily_email):
            result["email"] = tavily_email
            result["source"] = "tavily_web_search"
            result["confidence"] = "high"
            logger.info(f"Found email via Tavily for {company_name}: {tavily_email}")
            return result
    except Exception as te:
        logger.debug(f"Tavily email search error for {company_name}: {te}")

    # ── Step 4: Try scraping contact pages ───────────────────────────
    website_emails = find_emails_on_website(domain)
    for email in website_emails:
        if verify_email_deliverability(email):
            result["email"] = email
            result["source"] = "website_scrape"
            result["confidence"] = "high"
            logger.info(f"Found scraped and verified email for {company_name}: {email}")
            return result

    # ── Step 5: Fallback — common HR email patterns ───────────────────
    # Generates standard patterns and verifies active mail servers via MX query
    hr_patterns = [
        f"hr@{domain}",
        f"careers@{domain}",
        f"recruitment@{domain}",
        f"hiring@{domain}",
        f"talent@{domain}",
    ]
    
    for pattern in hr_patterns:
        if verify_email_deliverability(pattern):
            result["email"] = pattern
            result["source"] = "pattern_guess"
            result["confidence"] = "medium"
            logger.info(f"Using verified pattern email for {company_name}: {pattern}")
            return result

    # If no pattern email passes MX check, do NOT email this company to prevent bounces
    logger.warning(f"❌ No valid email could be verified for {company_name} (domain: {domain}). Skipping outreach.")
    return result
