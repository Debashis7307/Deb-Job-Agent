"""
agent/graph.py — LangGraph workflow definition
Wires all nodes into the job application agent graph.
"""
import logging
from datetime import datetime
from typing import Dict
from langgraph.graph import StateGraph, START, END
from agent.state import AgentState
from agent.nodes.scrape_node import scrape_jobs_node
from agent.nodes.filter_node import filter_deduplicate_node, score_and_rank_node
from agent.nodes.apply_node import auto_apply_node
from agent.nodes.email_node import email_node
from agent.nodes.memory_node import load_memory_node, save_memory_node
from agent.nodes.report_node import generate_report_node
from agent.nodes.pdf_outreach_node import pdf_outreach_node

logger = logging.getLogger(__name__)


def should_continue_after_filter(state: AgentState) -> str:
    """Conditional edge: If no new jobs found, skip job processing but still run PDF drip."""
    if not state.get("new_jobs"):
        logger.info("No new jobs found today. Jumping to PDF outreach.")
        return "pdf_outreach"
    return "score"


def build_job_agent_graph() -> StateGraph:
    """Build and compile the LangGraph job application workflow."""
    
    graph = StateGraph(AgentState)

    # ── Add all nodes ─────────────────────────────────────────────────
    graph.add_node("load_memory", load_memory_node)
    graph.add_node("scrape", scrape_jobs_node)
    graph.add_node("filter", filter_deduplicate_node)
    graph.add_node("score", score_and_rank_node)
    graph.add_node("apply", auto_apply_node)
    graph.add_node("email", email_node)
    graph.add_node("pdf_outreach", pdf_outreach_node)   # PDF HR daily drip
    graph.add_node("save_memory", save_memory_node)
    graph.add_node("report", generate_report_node)

    # ── Wire edges ────────────────────────────────────────────────────
    graph.add_edge(START, "load_memory")
    graph.add_edge("load_memory", "scrape")
    graph.add_edge("scrape", "filter")

    # Conditional: if no new jobs → skip to report
    graph.add_conditional_edges(
        "filter",
        should_continue_after_filter,
        {
            "score": "score",
            "pdf_outreach": "pdf_outreach",  # Still run PDF drip even if no jobs scraped
        }
    )

    graph.add_edge("score", "apply")
    graph.add_edge("apply", "email")
    graph.add_edge("email", "pdf_outreach")         # ← PDF HR drip runs after job email
    graph.add_edge("pdf_outreach", "save_memory")
    graph.add_edge("save_memory", "report")
    graph.add_edge("report", END)

    return graph.compile()


def get_initial_state(dry_run: bool = True) -> AgentState:
    """Create the initial state for a new run."""
    return AgentState(
        run_date=datetime.now().strftime("%Y-%m-%d"),
        dry_run=dry_run,
        raw_jobs=[],
        new_jobs=[],
        scored_jobs=[],
        jobs_to_apply=[],
        application_results=[],
        emails_to_send=[],
        emails_sent=[],
        total_scraped=0,
        total_new=0,
        total_applied=0,
        total_emailed=0,
        total_failed=0,
        pdf_emails_sent=0,
        report_html="",
        errors=[],
        memory_context="",
    )
