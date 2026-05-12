import requests
r = requests.get(
    'https://api.unsplash.com/photos/random',
    params={'query': 'test'},
    headers={'Authorization': 'Client-ID REDACTED_KEY'}
)
print(f"Status: {r.status_code}")
limit = r.headers.get("X-Ratelimit-Limit", "?")
remaining = r.headers.get("X-Ratelimit-Remaining", "?")
print(f"Limit: {limit}")
print(f"Remaining: {remaining}")
