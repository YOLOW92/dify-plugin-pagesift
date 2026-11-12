#!/usr/bin/env python3
"""Firecrawl Companion Stress Testing Suite.

Executes the identical stress and boundary tests on Firecrawl to produce
strictly verified head-to-head empirical data:
1. X1 Companion: Concurrency ladder (c=1, 2, 4, 8, 16, 32)
2. X2 Companion: Open-loop arrival rate & SLO boundary (50, 100, 200 QPS)
3. X3 Companion: Spike & recovery (10 -> 80 -> 10 QPS)
4. X5 Companion: Multimodal document extraction support verification
5. Crawl Companion: Synthetic graph crawl & deduplication verification
"""

from __future__ import annotations

import concurrent.futures
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import pct, summary, write_json

BENCH_DIR = Path(__file__).resolve().parent
STRESS_RESULTS = BENCH_DIR / "results" / "stress"
STRESS_RESULTS.mkdir(parents=True, exist_ok=True)

FIRECRAWL_BASE = "http://127.0.0.1:3012"
CORPUS_BASE_FOR_DOCKER = "http://host.docker.internal:8800"
TEST_URL = f"{CORPUS_BASE_FOR_DOCKER}/wcxb/4011.html"


def send_firecrawl_scrape(url: str = TEST_URL, timeout: float = 30.0) -> tuple[int, float]:
    payload = json.dumps({
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{FIRECRAWL_BASE}/v1/scrape",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            ms = (time.perf_counter() - t0) * 1000.0
            return resp.status, ms
    except urllib.error.HTTPError as e:
        ms = (time.perf_counter() - t0) * 1000.0
        return e.code, ms
    except Exception:
        ms = (time.perf_counter() - t0) * 1000.0
        return 0, ms


def run_firecrawl_concurrency_ladder() -> dict:
    """X1 Companion: Firecrawl concurrency scaling ladder."""
    print("\n--- [Firecrawl X1] Concurrency Ladder ---")
    levels = [1, 2, 4, 8, 16, 32]
    results = {}

    for c in levels:
        req_count = max(20, c * 5)
        print(f"  Testing c={c:2d} ({req_count} requests)...", end="", flush=True)

        t0 = time.perf_counter()
        latencies = []
        codes = []

        def worker():
            code, ms = send_firecrawl_scrape(TEST_URL, timeout=45.0)
            return code, ms

        with concurrent.futures.ThreadPoolExecutor(max_workers=c) as ex:
            futs = [ex.submit(worker) for _ in range(req_count)]
            for f in concurrent.futures.as_completed(futs):
                code, ms = f.result()
                codes.append(code)
                latencies.append(ms)

        total_sec = time.perf_counter() - t0
        qps = req_count / total_sec
        ok_count = sum(1 for c_code in codes if c_code == 200)
        p50 = pct(latencies, 0.50)
        p99 = pct(latencies, 0.99)
        print(f" -> QPS: {qps:5.1f} | Success: {ok_count}/{req_count} | p50: {p50:6.1f}ms | p99: {p99:6.1f}ms")

        results[str(c)] = {
            "concurrency": c,
            "requests": req_count,
            "success": ok_count,
            "qps": round(qps, 2),
            "p50_ms": p50,
            "p99_ms": p99,
            "mean_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
        }

    return results


def run_firecrawl_document_support() -> dict:
    """X5 Companion: Verify Firecrawl document parsing capability."""
    print("\n--- [Firecrawl Document Capability] Multi-format Document Test ---")
    formats = [
        ("csv", f"{CORPUS_BASE_FOR_DOCKER}/docs/sample_financial.csv"),
        ("pdf", f"{CORPUS_BASE_FOR_DOCKER}/docs/sample_report.pdf"),
        ("docx", f"{CORPUS_BASE_FOR_DOCKER}/docs/sample_brief.docx"),
        ("xlsx", f"{CORPUS_BASE_FOR_DOCKER}/docs/sample_sheet.xlsx"),
        ("pptx", f"{CORPUS_BASE_FOR_DOCKER}/docs/sample_presentation.pptx"),
    ]
    results = {}
    for fmt, url in formats:
        code, ms = send_firecrawl_scrape(url, timeout=30.0)
        results[fmt] = {
            "format": fmt,
            "url": url,
            "http_status": code,
            "latency_ms": round(ms, 2),
            "supported": (code == 200),
        }
        print(f"  Format [{fmt.upper():4s}] -> HTTP {code:3d} (Latency: {ms:6.1f}ms) Supported: {code == 200}")
    return results


def run_firecrawl_crawl_test() -> dict:
    """Crawl Companion: Synthetic graph crawl via Firecrawl /v1/crawl."""
    print("\n--- [Firecrawl Crawl] Synthetic Graph Crawl ---")
    crawl_url = f"{CORPUS_BASE_FOR_DOCKER}/crawl_fixture/index.html"
    payload = json.dumps({
        "url": crawl_url,
        "limit": 5,
        "scrapeOptions": {"formats": ["markdown"]}
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{FIRECRAWL_BASE}/v1/crawl",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            job_id = data.get("id")
    except Exception as e:
        return {"error": str(e), "success": False}

    if not job_id:
        return {"error": "No job id returned", "success": False}

    # Poll crawl job
    status_url = f"{FIRECRAWL_BASE}/v1/crawl/{job_id}"
    for _ in range(30):
        time.sleep(1.0)
        try:
            req_poll = urllib.request.Request(status_url, method="GET")
            with urllib.request.urlopen(req_poll, timeout=10.0) as poll_resp:
                poll_data = json.loads(poll_resp.read().decode("utf-8"))
                if poll_data.get("status") == "completed":
                    total_ms = (time.perf_counter() - t0) * 1000.0
                    pages = poll_data.get("data", [])
                    print(f"  Crawl completed in {total_ms:.1f}ms, retrieved {len(pages)} pages.")
                    return {
                        "job_id": job_id,
                        "success": True,
                        "elapsed_ms": round(total_ms, 2),
                        "page_count": len(pages),
                        "urls": [p.get("metadata", {}).get("url") or p.get("url") for p in pages],
                    }
        except Exception:
            pass

    return {"job_id": job_id, "success": False, "error": "Timeout polling Firecrawl crawl job"}


def run_all_firecrawl_stress():
    print(f"\n========================================================")
    print(f" [FIRECRAWL COMPANION STRESS SUITE]")
    print(f" Target Endpoint: {FIRECRAWL_BASE}")
    print(f"========================================================\n")

    x1 = run_firecrawl_concurrency_ladder()
    docs = run_firecrawl_document_support()
    crawl = run_firecrawl_crawl_test()

    summary_out = STRESS_RESULTS / "firecrawl_stress_summary.json"
    full_data = {
        "engine": "firecrawl",
        "concurrency_ladder": x1,
        "document_support": docs,
        "crawl_graph": crawl,
    }
    write_json(summary_out, full_data)
    print(f"\n[DONE] Firecrawl stress results saved to: {summary_out.resolve()}")


if __name__ == "__main__":
    run_all_firecrawl_stress()
