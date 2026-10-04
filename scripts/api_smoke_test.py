import json
import requests

url = "https://data.gov.sg/api/action/datastore_search"
params = {
    "resource_id": "d_8ef23381f9417e4d4254ee8b4dcdb176",
    "limit": 5,
    "offset": 0,
}

response = requests.get(url, params=params, timeout=30)
response.raise_for_status()
payload = response.json()

if payload.get("success") is not True:
    raise RuntimeError(f"API returned an error: {payload}")

records = payload["result"]["records"]
print("HTTP status:", response.status_code)
print("Total source rows:", payload["result"]["total"])
print(json.dumps(records, ensure_ascii=False, indent=2))
