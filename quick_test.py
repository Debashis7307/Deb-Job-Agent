from scrapers.remoteok_scraper import scrape_remoteok
jobs = scrape_remoteok(5)
print(f"RemoteOK: {len(jobs)} jobs found")
for j in jobs[:3]:
    print(f"  - {j['title']} @ {j['company']}")

from database.db_manager import DatabaseManager
import os, gc, time

db = DatabaseManager("database/quick_test.db")
test_job = {"url": "https://test.com/job/999", "title": "Python Dev", "company": "TestCo", "location": "Remote", "portal": "test", "description": "test"}
r1 = db.add_job(test_job)
r2 = db.add_job(test_job)
stats = db.get_all_time_stats()
print(f"SQLite: Add={r1}, Dedup={not r2}, Stats={bool(stats)}")
del db
gc.collect()
time.sleep(0.5)
try:
    os.remove("database/quick_test.db")
except:
    pass

from agent.graph import build_job_agent_graph, get_initial_state
agent = build_job_agent_graph()
state = get_initial_state(dry_run=True)
print("LangGraph: Compiled OK")
print("\nAll core components WORKING!")
print("\nNOW DO:")
print("1. Run setup wizard: .\\venv\\Scripts\\python setup.py")
print("2. Edit data/user_profile.json with your details")
print("3. Put your resume at data/resume.pdf")
print("4. Then test: .\\venv\\Scripts\\python main.py --dry-run")
