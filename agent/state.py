"""
agent/state.py — LangGraph AgentState TypedDict for the Job Application Agent
"""
from typing import TypedDict, List, Dict, Any, Optional, Annotated
from operator import add


class JobItem(TypedDict):
    """Represents a single job listing."""
    title: str
    company: str
    location: str
    url: str
    description: str
    portal: str
    relevance_score: float
    is_us_remote: bool
    is_internship: bool
    apply_url: Optional[str]
    hr_email: Optional[str]


class ApplicationResult(TypedDict):
    """Result of an application attempt."""
    job_url: str
    job_title: str
    company: str
    status: str        # "applied" | "failed" | "manual_required" | "email_sent"
    portal: str
    hr_email: Optional[str]
    email_sent: bool
    notes: str


class AgentState(TypedDict):
    """Full state for the LangGraph job application workflow."""

    # ── Run metadata ──────────────────────────────────────────────────
    run_date: str                    # Today's date YYYY-MM-DD
    dry_run: bool                    # True = no real applying/emailing

    # ── Scraping ──────────────────────────────────────────────────────
    raw_jobs: List[Dict]             # All scraped jobs (before filtering)
    new_jobs: List[Dict]             # Jobs that pass dedup + filter
    scored_jobs: List[Dict]          # Jobs ranked by relevance score

    # ── Applying ──────────────────────────────────────────────────────
    jobs_to_apply: List[Dict]        # Top N jobs selected for today
    application_results: Annotated[List[ApplicationResult], add]  # Accumulates

    # ── Email ─────────────────────────────────────────────────────────
    emails_to_send: List[Dict]       # Email data ready to send
    emails_sent: Annotated[List[Dict], add]

    # ── Stats ─────────────────────────────────────────────────────────
    total_scraped: int
    total_new: int
    total_applied: int
    total_emailed: int
    total_failed: int
    pdf_emails_sent: int           # Emails sent from PDF HR contact list today

    # ── Daily report ─────────────────────────────────────────────────
    report_html: str                 # HTML email report
    errors: Annotated[List[str], add]

    # ── mem0 memory ───────────────────────────────────────────────────
    memory_context: str              # Retrieved memories as text
