"""Debug CI LLM auth - run inside GitHub Actions to probe what the gateway returns."""

import hashlib
import os
import requests


def probe(model: str, headers: dict, url: str) -> None:
    payload = {
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": "PONG"}],
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        print(f"[{model}] HTTP", r.status_code)
        print(f"[{model}] Body head:", r.text[:300])
    except Exception as e:
        print(f"[{model}] ERR:", e)


def main() -> None:
    a = os.environ.get("LLM_AUTH", "")
    url = os.environ.get("LLM_URL", "")
    model = os.environ.get("LLM_MODEL", "")
    uid = os.environ.get("LLM_GATEWAY_UID", "")
    prod = os.environ.get("LLM_GATEWAY_PRODUCT", "")
    intent = os.environ.get("LLM_GATEWAY_INTENTION", "")

    print("LLM_AUTH len:", len(a))
    print("LLM_AUTH sha256:", hashlib.sha256(a.encode()).hexdigest())
    print("LLM_URL:", url)
    print("LLM_MODEL:", model)
    print("LLM_GATEWAY_UID:", uid)
    print("LLM_GATEWAY_PRODUCT:", prod)
    print("LLM_GATEWAY_INTENTION:", intent)

    auth = a if a.lower().startswith(("bearer ", "token ")) else f"Bearer {a}"
    headers = {
        "Authorization": auth,
        "AI-Gateway-Uid": uid,
        "AI-Gateway-Product-Name": prod,
        "AI-Gateway-Intention-Code": intent,
        "Content-Type": "application/json",
    }

    # Test multiple models to see which backend rejects
    probe("azure/gpt-5.5", headers, url)
    probe("gpt-5.5", headers, url)
    probe("gpt-4o", headers, url)
    probe("gpt-4o-mini", headers, url)


if __name__ == "__main__":
    main()
