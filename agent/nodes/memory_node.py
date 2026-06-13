"""
agent/nodes/memory_node.py — mem0 cloud memory + SQLite persistence

Tracks:
- Total applications sent (all time)
- Daily progress
- Company names to avoid re-applying  
- mem0: stores summary for cross-session context
"""
import logging
from datetime import datetime
from typing import Dict
from agent.state import AgentState
from database.db_manager import DatabaseManager
import config as cfg

logger = logging.getLogger(__name__)


def load_memory_node(state: AgentState) -> Dict:
    """
    LangGraph node: Load memory at the START of each run.
    Retrieves context from mem0 (if enabled) + SQLite stats.
    Guarded with a local 24h cache to minimize API calls under Hobby limits.
    """
    memory_lines = []
    db = DatabaseManager(cfg.DB_PATH)

    # ── SQLite stats ──────────────────────────────────────────────────
    all_time = db.get_all_time_stats()
    today = datetime.now().strftime("%Y-%m-%d")
    today_applied = db.get_today_applied_count()

    memory_lines.append(f"All-time applications: {all_time.get('total_applied', 0)}")
    memory_lines.append(f"All-time emails sent: {all_time.get('total_emailed', 0)}")
    memory_lines.append(f"Unique companies contacted: {all_time.get('unique_companies', 0)}")
    memory_lines.append(f"Today ({today}) already applied: {today_applied}")

    # ── mem0 cloud memory (optional) ─────────────────────────────────
    if cfg.USE_MEM0:
        try:
            import json
            import os
            from pathlib import Path
            
            cache_file = Path(cfg.DATA_DIR) / "mem0_cache.json"
            mem0_context = ""
            loaded_from_cache = False
            
            # Check cache first
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cache_data = json.load(f)
                    if cache_data.get("last_retrieval_date") == today:
                        mem0_context = cache_data.get("context", "")
                        loaded_from_cache = True
                        logger.info("mem0: Loaded search results from local 24h cache")
                except Exception as ce:
                    logger.warning(f"Failed reading mem0 cache: {ce}")
            
            if not loaded_from_cache:
                from mem0 import MemoryClient
                client = MemoryClient(api_key=cfg.MEM0_API_KEY)

                raw = client.search(
                    query="job applications today progress stats",
                    filters={"user_id": cfg.MEM0_USER_ID},
                    limit=5
                )
                memories = raw if isinstance(raw, list) else raw.get("results", [])

                if memories:
                    mem0_context = "\n".join([m.get("memory", "") for m in memories])
                    logger.info(f"mem0: Loaded {len(memories)} memories from cloud API")
                
                # Save cache
                try:
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump({
                            "last_retrieval_date": today,
                            "context": mem0_context
                        }, f, indent=2)
                except Exception as ce:
                    logger.warning(f"Failed writing mem0 cache: {ce}")

            if mem0_context:
                memory_lines.append(f"Previous context from memory:\n{mem0_context}")

        except Exception as e:
            logger.warning(f"mem0 load failed (non-critical): {e}")

    memory_context = "\n".join(memory_lines)
    logger.info(f"Memory loaded:\n{memory_context}")

    return {"memory_context": memory_context}


def save_memory_node(state: AgentState) -> Dict:
    """
    LangGraph node: Save today's progress to mem0 at the END of each run.
    Guarded with a local sync register to avoid redundant saves and protect API quota.
    """
    if not cfg.USE_MEM0:
        logger.info("mem0 not configured. Skipping cloud memory save.")
        return {}

    try:
        import json
        import os
        from pathlib import Path
        from mem0 import MemoryClient

        client = MemoryClient(api_key=cfg.MEM0_API_KEY)
        today = datetime.now().strftime("%Y-%m-%d")
        sync_file = Path(cfg.DATA_DIR) / "mem0_sync.json"

        total_applied = state.get("total_applied", 0)
        total_emailed = state.get("total_emailed", 0)
        total_scraped = state.get("total_scraped", 0)

        # Get companies applied to today
        application_results = state.get("application_results", [])
        companies_today = list({r["company"] for r in application_results if r.get("company")})[:10]

        summary = (
            f"On {today}: Scraped {total_scraped} jobs, "
            f"applied to {total_applied} jobs, "
            f"sent {total_emailed} cold emails. "
            f"Companies: {', '.join(companies_today)}"
        )

        # Check if already synced today with same stats
        if sync_file.exists():
            try:
                with open(sync_file, "r", encoding="utf-8") as f:
                    sync_data = json.load(f)
                if sync_data.get("last_sync_date") == today and sync_data.get("summary") == summary:
                    logger.info("mem0: Today's summary already synced to cloud. Skipping duplicate add request.")
                    return {}
            except Exception as ce:
                logger.warning(f"Failed reading mem0 sync cache: {ce}")

        client.add(
            summary,
            user_id=cfg.MEM0_USER_ID,
            metadata={"date": today, "type": "daily_summary"}
        )

        # Save sync status
        try:
            with open(sync_file, "w", encoding="utf-8") as f:
                json.dump({
                    "last_sync_date": today,
                    "summary": summary
                }, f, indent=2)
        except Exception as ce:
            logger.warning(f"Failed writing mem0 sync cache: {ce}")

        logger.info(f"✅ mem0: Saved daily summary: {summary}")

    except Exception as e:
        logger.warning(f"mem0 save failed (non-critical): {e}")

    return {}
