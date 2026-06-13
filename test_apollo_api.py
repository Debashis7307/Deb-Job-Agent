import requests
import json

api_key = "_8CQ6g0XhI0xJQNPlZqoMA"
domain = "amlgolabs.com"

headers = {
    "Content-Type": "application/json",
    "Cache-Control": "no-cache",
    "X-Api-Key": api_key
}

url_orgs = "https://api.apollo.io/v1/organizations/search"
payload_orgs = {
    "q_organization_domains_list": [domain],
    "per_page": 1
}
try:
    resp = requests.post(url_orgs, json=payload_orgs, headers=headers, timeout=10)
    print("Status Code:", resp.status_code)
    print("Full Response JSON:")
    print(json.dumps(resp.json(), indent=2))
except Exception as e:
    print("Error:", e)
