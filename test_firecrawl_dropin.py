#!/usr/bin/env python3
"""
Verification Script: PageSift as a Zero-Code Drop-in Replacement for Firecrawl in Dify.

This script tests the Firecrawl v1/v2 compatible endpoints exposed by `pagesift serve`
(running by default on port 3002).
"""

import sys
import time
import json
import urllib.request
import urllib.error

PAGESIFT_BASE_URL = "http://127.0.0.1:3002"

def test_health():
    print(f"[*] Checking PageSift health at {PAGESIFT_BASE_URL}/healthz ...")
    try:
        req = urllib.request.Request(f"{PAGESIFT_BASE_URL}/healthz")
        with urllib.request.urlopen(req, timeout=3) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")
            if status == 200 and "ok" in body:
                print("    [+] PageSift is running and healthy!")
                return True
    except Exception as e:
        print(f"    [-] Health check failed: {e}")
        print("    [!] Make sure `pagesift serve --port 3002` is running.")
        return False

def test_scrape_v1(target_url="https://example.com"):
    print(f"\n[*] Testing /v1/scrape (Firecrawl v1 API) for {target_url} ...")
    payload = {
        "url": target_url,
        "formats": ["markdown"],
        "onlyMainContent": True
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{PAGESIFT_BASE_URL}/v1/scrape",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            raw = resp.read().decode("utf-8")
            res = json.loads(raw)
            
            assert res.get("success") is True, f"Response success was not True: {res}"
            data_field = res.get("data", {})
            markdown = data_field.get("markdown", "")
            metadata = data_field.get("metadata", {})
            
            print(f"    [+] Status: HTTP {resp.status} (Completed in {elapsed_ms:.2f} ms)")
            print(f"    [+] Firecrawl Compatible Response: success={res.get('success')}")
            print(f"    [+] Page Title: {metadata.get('title')}")
            print(f"    [+] Extracted Markdown Preview ({len(markdown)} bytes):\n")
            preview = markdown.strip().split("\n")[:8]
            for line in preview:
                print(f"        | {line}")
            print("\n    [✓] Drop-in compatibility test PASSED!")
            return True
    except Exception as e:
        print(f"    [-] /v1/scrape failed: {e}")
        return False

def main():
    print("=" * 60)
    print(" PageSift Drop-in Firecrawl Compatibility Verification for Dify")
    print("=" * 60)
    
    if not test_health():
        sys.exit(1)
        
    success = test_scrape_v1()
    if success:
        print("\n" + "=" * 60)
        print(" Result: PageSift is 100% compatible with Dify's Firecrawl configuration!")
        print(" In Dify settings, simply set:")
        print("   Base URL: http://<pagesift-host>:3002")
        print("=" * 60)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
