"""
Delta Exchange API Key Diagnostic & Connectivity Verifier.
Checks credentials, dynamic clock offset, public IP whitelisting, and private wallet access.
"""

import os
import sys
import time
import email.utils
import hashlib
import hmac
import requests
from dotenv import load_dotenv

load_dotenv(override=True)


def get_public_ip():
    try:
        r = requests.get("https://api.ipify.org?format=json", timeout=4)
        return r.json().get("ip", "Unknown")
    except Exception:
        return "Unknown"


def main():
    print("=" * 70)
    print("DELTA EXCHANGE API KEY & CONNECTIVITY DIAGNOSTIC")
    print("=" * 70)

    api_key = os.getenv("DELTA_API_KEY", "").strip()
    api_secret = os.getenv("DELTA_API_SECRET", "").strip()
    env = os.getenv("DELTA_ENVIRONMENT", "india").lower()

    if not api_key or not api_secret:
        print("[!] ERROR: DELTA_API_KEY or DELTA_API_SECRET is missing in .env")
        print("    Please add them to your .env file and re-run.")
        sys.exit(1)

    masked_key = api_key[:4] + "..." + api_key[-4:] if len(api_key) > 8 else "***"
    print(f"API Key              : {masked_key}")
    print(f"Environment Config   : {env.upper()}")
    public_ip = get_public_ip()
    print(f"Your Outbound IP     : {public_ip}")
    print("-" * 70)

    endpoints = {
        "india": "https://api.india.delta.exchange",
        "global": "https://api.delta.exchange",
        "testnet": "https://testnet-api.delta.exchange"
    }

    base_url = endpoints.get(env, endpoints["india"])
    print(f"Testing against base URL: {base_url}")

    # 1. Exact local timestamp
    synced_ts = str(int(time.time()))
    path = "/v2/wallet/balances"
    message = "GET" + synced_ts + path
    signature = hmac.new(api_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()

    headers = {
        "api-key": api_key,
        "timestamp": synced_ts,
        "signature": signature,
        "Content-Type": "application/json"
    }

    print(f"Sending authenticated request to {path}...")
    try:
        res = requests.get(base_url + path, headers=headers, timeout=5)
        print(f"Response Status Code : {res.status_code}")

        if res.status_code == 200:
            print("[+] SUCCESS! API credentials are VALID and private wallet access is authorized.")
            data = res.json().get("result", [])
            print(f"    Balances returned for {len(data)} asset(s).")
            for b in data[:3]:
                print(f"    - Asset: {b.get('asset_symbol', 'N/A')}, Balance: {b.get('balance', 0)}")
            print("=" * 70)
            print("Your engine is ready to place live orders on Delta Exchange!")
            return

        print(f"[!] Server Error Response: {res.text}")
        print("-" * 70)
        print("DIAGNOSIS & HOW TO FIX:")
        data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
        err_code = data.get("error", {}).get("code", "")

        if err_code == "invalid_api_key":
            print("1. IP RESTRICTION: In your Delta Exchange account under API Keys,")
            print(f"   check if IP Whitelisting is active. Either leave IP Restriction BLANK")
            print(f"   or add your current IP address: {public_ip}")
            print("2. PERMISSIONS: Ensure the key has 'Trading' or 'Read & Write' permissions enabled.")
            print(f"3. PORTAL MISMATCH: Verify whether your key was created on India (india.delta.exchange),")
            print(f"   Global (delta.exchange), or Testnet (testnet.delta.exchange).")
            print("   Update DELTA_ENVIRONMENT in .env accordingly.")
        elif err_code == "expired_signature":
            print("Server time offset detected. Re-run after synchronizing Windows clock.")
        else:
            print("Unexpected response. Please review key permissions on Delta Exchange.")

    except Exception as e:
        print(f"[!] Network or Connection Error: {e}")

    print("=" * 70)


if __name__ == "__main__":
    main()

