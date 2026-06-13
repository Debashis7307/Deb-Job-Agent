"""
tools/pdf_hr_parser.py — Parse CompanyWise HR contact PDF into usable data

Strategy:
1. Parse PDF once → save to CSV at data/hr_contacts_from_pdf.csv
2. Expose get_next_pdf_hr_batch(count=50) → returns next unsent contacts
   (using the pdf_hr_outreach table in SQLite to track what's been sent)
3. Each contact: {name, company, designation, email}
"""
import logging
import re
import csv
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional
from datetime import date

logger = logging.getLogger(__name__)

# Paths
PDF_PATH = Path(__file__).parent.parent / "data" / "CompanyWise HR contact.pdf"
CSV_PATH = Path(__file__).parent.parent / "data" / "hr_contacts_from_pdf.csv"

EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')


# ── Database helpers ────────────────────────────────────────────────────────

def _get_db_conn():
    import config as cfg
    conn = sqlite3.connect(cfg.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_pdf_outreach_table():
    """Create pdf_hr_outreach table if not exists."""
    try:
        with _get_db_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pdf_hr_outreach (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    email      TEXT UNIQUE NOT NULL,
                    name       TEXT,
                    company    TEXT,
                    designation TEXT,
                    sent_date  TEXT,
                    status     TEXT DEFAULT 'pending'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pdf_status ON pdf_hr_outreach(status)")
    except Exception as e:
        logger.warning(f"pdf_hr_outreach table init error: {e}")


def is_pdf_email_sent(email: str) -> bool:
    """Return True if this email was already sent from the PDF list."""
    try:
        with _get_db_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM pdf_hr_outreach WHERE email = ? AND status = 'sent'", (email.lower(),)
            ).fetchone()
        return row is not None
    except Exception:
        return False


def mark_pdf_hr_sent(email: str, name: str, company: str, designation: str, status: str = "sent"):
    """Mark an HR contact as emailed."""
    _init_pdf_outreach_table()
    today = date.today().isoformat()
    email = email.lower().strip()
    try:
        with _get_db_conn() as conn:
            conn.execute("""
                INSERT INTO pdf_hr_outreach (email, name, company, designation, sent_date, status)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET status=excluded.status, sent_date=excluded.sent_date
            """, (email, name, company, designation, today, status))
    except Exception as e:
        logger.warning(f"mark_pdf_hr_sent error: {e}")


def get_pdf_hr_sent_count_today() -> int:
    """How many PDF HR emails sent today."""
    today = date.today().isoformat()
    try:
        with _get_db_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM pdf_hr_outreach WHERE sent_date = ? AND status = 'sent'",
                (today,)
            ).fetchone()
        return row["cnt"] if row else 0
    except Exception:
        return 0


# ── PDF Parsing ──────────────────────────────────────────────────────────────

def _parse_pdf_to_csv() -> int:
    """
    Parse the PDF and save all contacts to CSV.
    Returns number of contacts extracted.
    Only runs if CSV doesn't already exist.
    """
    if CSV_PATH.exists():
        # Count existing rows
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            count = sum(1 for _ in f) - 1  # minus header
        logger.info(f"PDF already parsed: {count} contacts in {CSV_PATH.name}")
        return count

    if not PDF_PATH.exists():
        logger.error(f"HR contacts PDF not found at: {PDF_PATH}")
        return 0

    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber not installed. Run: pip install pdfplumber")
        return 0

    contacts = []
    logger.info(f"Parsing HR contacts PDF: {PDF_PATH.name} ...")

    try:
        with pdfplumber.open(PDF_PATH) as pdf:
            logger.info(f"PDF has {len(pdf.pages)} pages")
            for page_num, page in enumerate(pdf.pages, 1):
                # Try table extraction first
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        for row in table:
                            contact = _parse_row_from_table(row)
                            if contact:
                                contacts.append(contact)
                else:
                    # Fallback: raw text extraction
                    text = page.extract_text() or ""
                    page_contacts = _parse_text_for_contacts(text)
                    contacts.extend(page_contacts)

                if page_num % 10 == 0:
                    logger.info(f"  Processed page {page_num}/{len(pdf.pages)}, {len(contacts)} contacts so far...")

    except Exception as e:
        logger.error(f"PDF parsing failed: {e}", exc_info=True)
        return 0

    # Deduplicate by email
    seen_emails = set()
    unique_contacts = []
    for c in contacts:
        email = c.get("email", "").lower().strip()
        if email and email not in seen_emails and "@" in email:
            seen_emails.add(email)
            unique_contacts.append(c)

    # Write to CSV
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "company", "designation", "email"])
        writer.writeheader()
        writer.writerows(unique_contacts)

    logger.info(f"✅ PDF parsed: {len(unique_contacts)} unique HR contacts saved to {CSV_PATH.name}")
    return len(unique_contacts)


def _parse_row_from_table(row: list) -> Optional[Dict]:
    """Extract contact info from a PDF table row."""
    if not row or len(row) < 2:
        return None

    # Flatten row to strings
    cells = [str(c).strip() if c else "" for c in row]
    full_text = " ".join(cells)

    # Must have an email
    emails = EMAIL_RE.findall(full_text)
    if not emails:
        return None

    email = emails[0].lower()
    # Skip generic/invalid emails
    if any(bad in email for bad in ["example", "test", "noreply", "no-reply", "admin@", "info@support"]):
        return None

    # Try to extract fields by position or keyword matching
    name = ""
    company = ""
    designation = ""

    # Common layouts: [Name, Company, Designation, Email] or [Company, Name, Email]
    name_candidates = [c for c in cells if c and not EMAIL_RE.search(c) and len(c) > 2]

    if len(name_candidates) >= 3:
        # Assume: Name | Company | Designation
        name = name_candidates[0][:80]
        company = name_candidates[1][:80]
        designation = name_candidates[2][:80]
    elif len(name_candidates) == 2:
        name = name_candidates[0][:80]
        company = name_candidates[1][:80]
    elif len(name_candidates) == 1:
        # Could be company or name — check designation keywords
        kw = name_candidates[0].lower()
        if any(w in kw for w in ["hr", "manager", "recruiter", "director", "head", "officer"]):
            designation = name_candidates[0][:80]
        else:
            company = name_candidates[0][:80]

    return {"name": name, "company": company, "designation": designation, "email": email}


def _parse_text_for_contacts(text: str) -> List[Dict]:
    """
    Fallback: parse raw text page for email patterns + surrounding context.
    Looks for lines with emails and tries to extract name/company from nearby text.
    """
    contacts = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    for i, line in enumerate(lines):
        emails = EMAIL_RE.findall(line)
        if not emails:
            continue

        email = emails[0].lower()
        if any(bad in email for bad in ["example", "noreply", "no-reply"]):
            continue

        # Grab context from surrounding lines
        ctx_lines = lines[max(0, i-2):i] + lines[i+1:min(len(lines), i+3)]
        name, company, designation = _guess_fields_from_context(email, line, ctx_lines)

        contacts.append({
            "name": name,
            "company": company,
            "designation": designation,
            "email": email,
        })

    return contacts


def _guess_fields_from_context(email: str, email_line: str, context: List[str]) -> tuple:
    """Guess name/company/designation from email and surrounding text."""
    name = ""
    company = ""
    designation = ""

    hr_keywords = ["hr", "human resource", "recruiter", "talent", "hiring", "head of people",
                   "people ops", "manager", "director", "officer", "lead", "founder", "ceo", "cto"]

    for line in context:
        line_lower = line.lower()
        if any(kw in line_lower for kw in hr_keywords) and not designation:
            designation = line[:80]
        elif len(line.split()) <= 5 and not name:
            # Short line is likely a person's name
            name = line[:60]
        elif not company:
            # Longer line is likely company info
            company = line[:80]

    # Try extracting name from email prefix
    if not name:
        prefix = email.split("@")[0]
        if "." in prefix:
            parts = prefix.split(".")
            name = " ".join(p.capitalize() for p in parts if p.isalpha())[:60]

    return name, company, designation


# ── Main exported function ────────────────────────────────────────────────────

def get_next_pdf_hr_batch(count: int = 50) -> List[Dict]:
    """
    Get the next batch of HR contacts from the PDF who haven't been emailed yet.
    
    1. Parses PDF → CSV (one-time setup)
    2. Reads CSV
    3. Filters out already-sent emails (from pdf_hr_outreach table)
    4. Returns next `count` contacts
    
    Returns list of dicts: {name, company, designation, email}
    """
    _init_pdf_outreach_table()

    # Parse PDF → CSV if not done yet
    total = _parse_pdf_to_csv()
    if total == 0:
        logger.warning("No HR contacts available from PDF.")
        return []

    # Get already-sent emails
    try:
        with _get_db_conn() as conn:
            rows = conn.execute(
                "SELECT email FROM pdf_hr_outreach WHERE status = 'sent'"
            ).fetchall()
        sent_emails = {r["email"].lower() for r in rows}
    except Exception:
        sent_emails = set()

    # Read CSV and filter
    contacts = []
    try:
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                email = row.get("email", "").lower().strip()
                if email and email not in sent_emails:
                    contacts.append({
                        "name": row.get("name", "").strip(),
                        "company": row.get("company", "").strip(),
                        "designation": row.get("designation", "").strip(),
                        "email": email,
                    })
                if len(contacts) >= count:
                    break
    except Exception as e:
        logger.error(f"Error reading HR contacts CSV: {e}")
        return []

    logger.info(f"PDF HR batch: {len(contacts)} contacts ready (from {total} total, {len(sent_emails)} already sent)")
    return contacts


def get_pdf_hr_stats() -> Dict:
    """Return stats about the PDF HR contact list."""
    _init_pdf_outreach_table()

    total_in_csv = 0
    if CSV_PATH.exists():
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            total_in_csv = sum(1 for _ in f) - 1  # minus header

    try:
        with _get_db_conn() as conn:
            row = conn.execute("""
                SELECT 
                    COALESCE(COUNT(*), 0) as total_sent,
                    COALESCE(SUM(CASE WHEN sent_date = date('now') THEN 1 ELSE 0 END), 0) as sent_today
                FROM pdf_hr_outreach WHERE status = 'sent'
            """).fetchone()
        total_sent = int(row["total_sent"]) if row else 0
        sent_today = int(row["sent_today"]) if row else 0
    except Exception:
        total_sent = 0
        sent_today = 0

    return {
        "total_in_pdf": total_in_csv,
        "total_sent": total_sent,
        "sent_today": sent_today,
        "remaining": max(0, total_in_csv - total_sent),
    }


if __name__ == "__main__":
    """Quick test: parse the PDF and show 5 sample contacts."""
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("\n[TEST] PDF HR Parser Starting...\n")
    
    batch = get_next_pdf_hr_batch(count=5)
    stats = get_pdf_hr_stats()
    
    print(f"\n[STATS] {stats}")
    print(f"\n[SAMPLE] First 5 contacts from PDF:")
    for i, c in enumerate(batch, 1):
        print(f"  {i}. {c['name']} | {c['company']} | {c['designation']} | {c['email']}")
    
    if not batch:
        print("  (No contacts found -- PDF may need to be reviewed)")
