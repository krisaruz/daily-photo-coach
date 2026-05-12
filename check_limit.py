import os
import sys

import yaml
import requests

config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
if os.path.exists(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    access_key = cfg.get("unsplash", {}).get("access_key", "")
else:
    access_key = os.environ.get("UNSPLASH_ACCESS_KEY", "")

if not access_key or access_key.startswith("$"):
    print("Error: UNSPLASH_ACCESS_KEY not configured. Set it in config.yaml or env var.")
    sys.exit(1)

r = requests.get(
    "https://api.unsplash.com/photos/random",
    params={"query": "test"},
    headers={"Authorization": f"Client-ID {access_key}"},
)
print(f"Status: {r.status_code}")
limit = r.headers.get("X-Ratelimit-Limit", "?")
remaining = r.headers.get("X-Ratelimit-Remaining", "?")
print(f"Limit: {limit}")
print(f"Remaining: {remaining}")
