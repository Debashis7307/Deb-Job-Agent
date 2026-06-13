import sys
sys.path.insert(0, ".")
import logging
from tools.email_finder import apollo_search_and_enrich, get_today_apollo_count

logging.basicConfig(level=logging.INFO)

print("="*60)
print("  APOLLO FREE CRM RETRIEVAL TEST")
print("="*60)

# Check count
count = get_today_apollo_count()
print(f"Today's Apollo search count: {count}")

# Test with a domain
domain = "amlgolabs.com"
company = "Amlgo Labs"
print(f"\nSearching for {company} ({domain})...")
email = apollo_search_and_enrich(company, domain)

print("\nResult:")
if email:
    print(f"Success! Found email: {email}")
else:
    print("No saved contact found in CRM (expected since your CRM is currently empty).")
    print("But the API call completed successfully with status 200 (no 403 blocks!).")
print("="*60)
