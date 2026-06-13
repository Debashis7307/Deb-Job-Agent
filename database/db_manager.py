"""
database/db_manager.py — SQLite database manager for tracking applications
"""
import sqlite3
import hashlib
import json
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages SQLite database for job application tracking."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_hash TEXT UNIQUE NOT NULL,
                    job_url TEXT,
                    job_title TEXT,
                    company TEXT,
                    location TEXT,
                    portal TEXT,
                    job_description TEXT,
                    status TEXT DEFAULT 'pending',
                    applied_date TEXT,
                    hr_email TEXT,
                    email_sent INTEGER DEFAULT 0,
                    email_sent_date TEXT,
                    relevance_score REAL DEFAULT 0,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS daily_stats (
                    date TEXT PRIMARY KEY,
                    total_scraped INTEGER DEFAULT 0,
                    total_new INTEGER DEFAULT 0,
                    total_applied INTEGER DEFAULT 0,
                    total_emailed INTEGER DEFAULT 0,
                    total_failed INTEGER DEFAULT 0,
                    run_time_seconds REAL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS hr_contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company TEXT,
                    company_domain TEXT,
                    hr_name TEXT,
                    hr_email TEXT,
                    source TEXT,
                    verified INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(company_domain, hr_email)
                );

                CREATE TABLE IF NOT EXISTS pdf_hr_outreach (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    email       TEXT UNIQUE NOT NULL,
                    name        TEXT,
                    company     TEXT,
                    designation TEXT,
                    sent_date   TEXT,
                    status      TEXT DEFAULT 'pending'
                );

                CREATE TABLE IF NOT EXISTS tavily_usage (
                    date  TEXT PRIMARY KEY,
                    count INTEGER DEFAULT 0
                );
                
                CREATE INDEX IF NOT EXISTS idx_job_hash ON applications(job_hash);
                CREATE INDEX IF NOT EXISTS idx_status ON applications(status);
                CREATE INDEX IF NOT EXISTS idx_applied_date ON applications(applied_date);
                CREATE INDEX IF NOT EXISTS idx_pdf_status ON pdf_hr_outreach(status);
            """)
        logger.info(f"Database initialized at {self.db_path}")

    @staticmethod
    def make_job_hash(job_url: str) -> str:
        """Create unique hash for a job URL."""
        return hashlib.sha256(job_url.encode()).hexdigest()[:16]

    def is_already_seen(self, job_url: str) -> bool:
        """Check if job was already successfully applied to or emailed.
        Jobs with 'new' or 'manual_required' status are retried (they weren't actually sent).
        """
        job_hash = self.make_job_hash(job_url)
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT status FROM applications WHERE job_hash = ?", (job_hash,)
            ).fetchone()
        if row is None:
            return False
        # Only skip if we actually applied or emailed
        return row[0] in ("applied", "email_sent")

    def add_job(self, job: dict) -> bool:
        """
        Add a new job to the database.
        Returns True if added, False if already exists.
        """
        job_hash = self.make_job_hash(job["url"])
        
        # If job already exists in DB with ANY status, do not add it again
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM applications WHERE job_hash = ?", (job_hash,)
            ).fetchone()
        if row is not None:
            return False

        with self._get_conn() as conn:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO applications 
                    (job_hash, job_url, job_title, company, location, portal, 
                     job_description, relevance_score, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new')
                """, (
                    job_hash,
                    job.get("url", ""),
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("location", ""),
                    job.get("portal", ""),
                    job.get("description", "")[:2000],
                    job.get("relevance_score", 0),
                ))
                return True
            except sqlite3.IntegrityError:
                return False

    def update_application_status(self, job_url: str, status: str, notes: str = ""):
        """Update the status of an application."""
        job_hash = self.make_job_hash(job_url)
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE applications 
                SET status = ?, applied_date = ?, notes = ?
                WHERE job_hash = ?
            """, (status, datetime.now().isoformat(), notes, job_hash))

    def mark_email_sent(self, job_url: str, hr_email: str):
        """Mark that a cold email was sent for this job."""
        job_hash = self.make_job_hash(job_url)
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE applications
                SET hr_email = ?, email_sent = 1, email_sent_date = ?
                WHERE job_hash = ?
            """, (hr_email, datetime.now().isoformat(), job_hash))

    def add_hr_contact(self, company: str, domain: str, hr_name: str, email: str, source: str):
        """Store an HR contact."""
        with self._get_conn() as conn:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO hr_contacts 
                    (company, company_domain, hr_name, hr_email, source)
                    VALUES (?, ?, ?, ?, ?)
                """, (company, domain, hr_name, email, source))
            except Exception:
                pass

    def update_daily_stats(self, date: str, **kwargs):
        """Upsert daily statistics."""
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT * FROM daily_stats WHERE date = ?", (date,)
            ).fetchone()

            if existing:
                updates = ", ".join(f"{k} = {k} + ?" for k in kwargs)
                conn.execute(
                    f"UPDATE daily_stats SET {updates} WHERE date = ?",
                    list(kwargs.values()) + [date]
                )
            else:
                cols = "date, " + ", ".join(kwargs.keys())
                vals = "?, " + ", ".join("?" * len(kwargs))
                conn.execute(
                    f"INSERT INTO daily_stats ({cols}) VALUES ({vals})",
                    [date] + list(kwargs.values())
                )

    def get_daily_stats(self, date: str) -> dict:
        """Get stats for a specific date."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM daily_stats WHERE date = ?", (date,)
            ).fetchone()
        return dict(row) if row else {}

    def get_all_time_stats(self) -> dict:
        """Get aggregated all-time statistics."""
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT 
                    COUNT(*) as total_jobs_seen,
                    SUM(CASE WHEN status = 'applied' THEN 1 ELSE 0 END) as total_applied,
                    SUM(CASE WHEN email_sent = 1 THEN 1 ELSE 0 END) as total_emailed,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as total_failed,
                    COUNT(DISTINCT company) as unique_companies
                FROM applications
            """).fetchone()
        return dict(row) if row else {}

    def get_recent_applications(self, days: int = 7) -> list:
        """Get applications from the last N days."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT job_title, company, portal, status, applied_date, email_sent
                FROM applications
                WHERE applied_date >= datetime('now', ?)
                ORDER BY applied_date DESC
            """, (f"-{days} days",)).fetchall()
        return [dict(r) for r in rows]

    def get_today_applied_count(self) -> int:
        """How many jobs applied today."""
        today = datetime.now().strftime("%Y-%m-%d")
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) as cnt FROM applications
                WHERE applied_date LIKE ? AND status IN ('applied', 'email_sent')
            """, (f"{today}%",)).fetchone()
        return row["cnt"] if row else 0

    def get_pending_for_email(self, limit: int = 25) -> list:
        """Get applied jobs where email hasn't been sent yet."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM applications
                WHERE status = 'applied' AND email_sent = 0
                ORDER BY relevance_score DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ── PDF HR Outreach ─────────────────────────────────────────────────────

    def get_pdf_hr_batch(self, limit: int = 50) -> list:
        """Return next unsent PDF HR contacts."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT email, name, company, designation
                FROM pdf_hr_outreach
                WHERE status != 'sent'
                ORDER BY id ASC
                LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def bulk_insert_pdf_contacts(self, contacts: list):
        """Insert PDF contacts into pdf_hr_outreach (ignores duplicates)."""
        with self._get_conn() as conn:
            conn.executemany("""
                INSERT OR IGNORE INTO pdf_hr_outreach (email, name, company, designation)
                VALUES (:email, :name, :company, :designation)
            """, contacts)
        logger.info(f"Bulk inserted {len(contacts)} PDF HR contacts into DB")

    def mark_pdf_hr_sent(self, email: str, status: str = "sent"):
        """Mark a PDF HR contact as emailed."""
        today = datetime.now().strftime("%Y-%m-%d")
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE pdf_hr_outreach
                SET status = ?, sent_date = ?
                WHERE email = ?
            """, (status, today, email.lower()))

    def get_pdf_hr_stats(self) -> dict:
        """Return stats on PDF HR outreach."""
        today = datetime.now().strftime("%Y-%m-%d")
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT
                    COALESCE(COUNT(*), 0) as total,
                    COALESCE(SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END), 0) as sent,
                    COALESCE(SUM(CASE WHEN sent_date = ? AND status = 'sent' THEN 1 ELSE 0 END), 0) as sent_today
                FROM pdf_hr_outreach
            """, (today,)).fetchone()
        if not row:
            return {"total": 0, "sent": 0, "sent_today": 0}
        return {
            "total": int(row["total"]),
            "sent": int(row["sent"]),
            "sent_today": int(row["sent_today"]),
        }
