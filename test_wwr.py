import requests
from bs4 import BeautifulSoup

RSS_URL = "https://weworkremotely.com/categories/remote-programming-jobs.rss"

print("Fetching WWR RSS feed...")
try:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    resp = requests.get(RSS_URL, headers=headers, timeout=15)
    print("Status Code:", resp.status_code)
    
    # We parse as xml using lxml or html.parser since xml might not be installed
    soup = BeautifulSoup(resp.content, "xml")
    items = soup.find_all("item")
    print(f"Total items found: {len(items)}")
    
    for i, item in enumerate(items[:3]):
        title_text = item.find("title").text if item.find("title") else ""
        link = item.find("link").text if item.find("link") else ""
        print(f"\nItem {i+1}:")
        print(f"  Raw Title: {title_text}")
        print(f"  Link:      {link}")
except Exception as e:
    print("Error:", e)
