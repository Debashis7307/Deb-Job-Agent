"""
test_agent.py — Quick test script to validate the agent setup
Tests each component independently without applying or sending emails.

Usage: .\\venv\\Scripts\\python test_agent.py
"""
import sys
import os
import io
from pathlib import Path

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

print("\n" + "="*60)
print("  [TEST] JOB AGENT - COMPONENT TEST")
print("="*60)

errors = []
passed = []

# ── Test 1: Config loading ────────────────────────────────────────────
print("\n[1/6] Testing config loading...")
try:
    import config as cfg
    assert cfg.GEMINI_API_KEY, "GEMINI_API_KEY missing"
    assert cfg.GMAIL_ADDRESS, "GMAIL_ADDRESS missing"
    passed.append("✅ Config loaded OK")
    print(f"  Gemini model: {cfg.GEMINI_MODEL}")
    print(f"  Gmail: {cfg.GMAIL_ADDRESS}")
    print(f"  Dry run: {cfg.DRY_RUN}")
    print(f"  LinkedIn: {'enabled' if cfg.USE_LINKEDIN else 'disabled'}")
    print(f"  Naukri: {'enabled' if cfg.USE_NAUKRI else 'disabled'}")
    print(f"  mem0: {'enabled' if cfg.USE_MEM0 else 'disabled'}")
except Exception as e:
    errors.append(f"❌ Config error: {e}")
    print(f"  ERROR: {e}")

# ── Test 2: Database ──────────────────────────────────────────────────
print("\n[2/6] Testing SQLite database...")
try:
    from database.db_manager import DatabaseManager
    test_db_path = "database/test_tracker.db"
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except Exception:
            pass
    db = DatabaseManager(test_db_path)
    
    # Test add job
    test_job = {
        "url": "https://test.example.com/job/123",
        "title": "Test Python Developer",
        "company": "TestCorp",
        "location": "Remote",
        "portal": "test",
        "description": "Test job description",
    }
    added = db.add_job(test_job)
    assert added, "Job should be added"
    
    # Test duplicate prevention
    added_again = db.add_job(test_job)
    assert not added_again, "Duplicate should be rejected"
    
    # Test stats
    stats = db.get_all_time_stats()
    
    # Cleanup test DB
    try:
        import gc
        del db
        gc.collect()
        import time
        time.sleep(0.5)
        os.remove("database/test_tracker.db")
    except Exception:
        pass  # File may be locked, it's just a test file
    
    passed.append("[PASS] Database OK (add, dedup, stats)")
    print("  SQLite add, dedup, and stats: OK")
except Exception as e:
    errors.append(f"❌ Database error: {e}")
    print(f"  ERROR: {e}")

# ── Test 3: RemoteOK scraper ──────────────────────────────────────────
print("\n[3/6] Testing RemoteOK scraper (live API)...")
try:
    from scrapers.remoteok_scraper import scrape_remoteok
    jobs = scrape_remoteok(max_jobs=5)
    assert isinstance(jobs, list), "Should return a list"
    passed.append(f"✅ RemoteOK scraper: {len(jobs)} jobs found")
    print(f"  Found {len(jobs)} jobs from RemoteOK API")
    if jobs:
        print(f"  Sample: {jobs[0].get('title')} @ {jobs[0].get('company')}")
except Exception as e:
    errors.append(f"❌ RemoteOK scraper error: {e}")
    print(f"  ERROR: {e}")

# ── Test 4: Gemini API ────────────────────────────────────────────────
print("\n[4/6] Testing Gemini API connection...")
try:
    from google import genai
    client = genai.Client(api_key=cfg.GEMINI_API_KEY)
    
    # Simple test call
    resp = client.models.generate_content(
        model=cfg.GEMINI_MODEL,
        contents="Reply with just: OK"
    )
    result = resp.text.strip()
    
    passed.append(f"[PASS] Gemini API working: responded '{result[:20]}'")
    print(f"  Gemini Flash response: '{result[:30]}'")
except Exception as e:
    errors.append(f"[FAIL] Gemini API error: {e}")
    print(f"  ERROR: {e}")
    print("  --> Check your GEMINI_API_KEY in .env")

# ── Test 5: Email sender (dry run) ────────────────────────────────────
print("\n[5/6] Testing email sender (dry run only)...")
try:
    from tools.email_sender import EmailSender
    sender = EmailSender(
        gmail_address=cfg.GMAIL_ADDRESS,
        app_password=cfg.GMAIL_APP_PASSWORD,
        resume_path=cfg.RESUME_PATH,
    )
    result = sender.send_cold_email(
        to_email="test@example.com",
        subject="Test",
        body="Test body",
        dry_run=True  # DRY RUN - won't actually send
    )
    assert result, "Dry run should succeed"
    passed.append("✅ Email sender (dry run): OK")
    print("  EmailSender dry-run: OK")
    
    resume_path = Path(cfg.RESUME_PATH)
    if not resume_path.exists():
        print(f"  ⚠️  WARNING: Resume not found at {cfg.RESUME_PATH}")
        print(f"     → Add your resume.pdf to data/ folder")
    else:
        print(f"  ✅ Resume found: {resume_path}")
except Exception as e:
    errors.append(f"❌ Email sender error: {e}")
    print(f"  ERROR: {e}")

# ── Test 6: LangGraph workflow ────────────────────────────────────────
print("\n[6/6] Testing LangGraph workflow compilation...")
try:
    from agent.graph import build_job_agent_graph, get_initial_state
    agent = build_job_agent_graph()
    initial_state = get_initial_state(dry_run=True)
    passed.append("✅ LangGraph graph compiled successfully")
    print("  Graph compiled and initial state created: OK")
except Exception as e:
    errors.append(f"❌ LangGraph error: {e}")
    print(f"  ERROR: {e}")

# ── Summary ───────────────────────────────────────────────────────────
print("\n" + "="*60)
print(f"  RESULTS: {len(passed)}/{len(passed)+len(errors)} tests passed")
print("="*60)

for p in passed:
    print(f"  {p}")

if errors:
    print("\n  FAILURES:")
    for e in errors:
        print(f"  {e}")
    print("\n  Fix the above errors, then run again.")
else:
    print("\n  🎉 ALL TESTS PASSED!")
    print("\n  Next: Run the agent in dry-run mode:")
    print("    .\\venv\\Scripts\\python main.py --dry-run")

print()
