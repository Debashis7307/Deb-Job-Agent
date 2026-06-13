"""Quick test of the new email finder with real companies from today's run."""
import sys, os
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv()

from tools.email_finder import find_hr_email

# Real companies from today's scrape
test_cases = [
    ("Honeywell",          "https://remoteok.com/jobs/123"),
    ("Bored Panda",        "https://remoteok.com/jobs/456"),
    ("Symonis",            "https://internshala.com/internship/detail/abc"),
    ("Zenerative Minds LLP", "https://internshala.com/internship/detail/xyz"),
    ("TSTEPS PRIVATE LIMITED", "https://internshala.com/internship/detail/tsteps"),
    ("Projectpedia Official Page", "https://remoteok.com/remote-jobs/projectpedia"),
]

print("="*60)
print("  EMAIL FINDER TEST")
print("="*60)

found = 0
for company, url in test_cases:
    result = find_hr_email(company, url)
    email = result.get("email", "")
    source = result.get("source", "")
    conf = result.get("confidence", "")
    domain = result.get("domain", "")
    status = "✅" if email else "❌"
    print(f"\n{status} {company}")
    print(f"   Domain : {domain}")
    print(f"   Email  : {email}")
    print(f"   Source : {source} ({conf})")
    if email:
        found += 1

print(f"\n{'='*60}")
print(f"  RESULT: {found}/{len(test_cases)} emails found")
print("="*60)
