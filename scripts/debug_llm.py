"""Debug CI LLM auth - run inside GitHub Actions to probe what the gateway returns."""

import os
import requests


def main() -> None:
    a = os.environ.get("LLM_AUTH", "")
    url = os.environ.get("LLM_URL", "")
    model = os.environ.get("LLM_MODEL", "")
    uid = os.environ.get("LLM_GATEWAY_UID", "")
    prod = os.environ.get("LLM_GATEWAY_PRODUCT", "")
    intent = os.environ.get("LLM_GATEWAY_INTENTION", "")

    print("LLM_AUTH len:", len(a))
    print("LLM_AUTH starts_with_bearer:", a.lower().startswith("bearer "))
    auth = a if a.lower().startswith(("bearer ", "token ")) else f"Bearer {a}"
    print("auth header len:", len(auth))

    headers = {
        "Authorization": auth,
        "AI-Gateway-Uid": uid,
        "AI-Gateway-Product-Name": prod,
        "AI-Gateway-Intention-Code": intent,
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": "PONG"}],
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        print("HTTP", r.status_code)
        print("Body head:", r.text[:500])
    except Exception as e:
        print("ERR:", e)


if __name__ == "__main__":
    main()
