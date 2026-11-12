"""Execute full WCXB Test Split (511 pages) benchmark evaluation."""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import post_json, read_jsonl, write_json

BENCH_DIR = Path(__file__).resolve().parent
CORPUS_DIR = BENCH_DIR / "corpus"
RESULTS_DIR = BENCH_DIR / "results" / "raw"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

MANIFEST_FILE = CORPUS_DIR / "wcxb_test511.jsonl"
PAGESIFT_BASE = "http://127.0.0.1:3002"
CORPUS_BASE = "http://127.0.0.1:8800"


def scrape_page(item: dict) -> dict:
    fid = item["id"]
    local_url = f"{CORPUS_BASE}/wcxb_test/html/{fid}.html"
    payload = {
        "url": local_url,
        "formats": ["markdown"],
        "onlyMainContent": True
    }
    status, body, ms, err = post_json(f"{PAGESIFT_BASE}/v2/scrape", payload, timeout=10.0)
    ok = (status == 200 and isinstance(body, dict) and body.get("success") is True)
    md = body.get("data", {}).get("markdown", "") if ok else ""

    return {
        "id": fid,
        "url": item["url"],
        "ok": ok,
        "ms": round(ms, 3),
        "status": status,
        "markdown": md,
        "error": err if not ok else None
    }


def run_test_split(concurrency: int = 4):
    items = read_jsonl(MANIFEST_FILE)
    print(f"[WCXB TEST 511] Running full test split of {len(items)} pages with concurrency={concurrency}...")

    t0 = time.perf_counter()
    results = []

    if concurrency == 1:
        for idx, it in enumerate(items, 1):
            res = scrape_page(it)
            results.append(res)
            if idx % 50 == 0:
                print(f"  -> [{idx}/{len(items)}] Processed... (last: {res['ms']} ms, ok={res['ok']})")
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(scrape_page, it) for it in items]
            for idx, fut in enumerate(concurrent.futures.as_completed(futures), 1):
                results.append(fut.result())
                if idx % 50 == 0:
                    print(f"  -> [{idx}/{len(items)}] Concurrent completed...")

    elapsed = time.perf_counter() - t0
    ok_count = sum(1 for r in results if r["ok"])
    qps = len(results) / elapsed

    out_jsonl = RESULTS_DIR / f"pagesift-wcxb_test511-v2-c{concurrency}.jsonl"
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for r in sorted(results, key=lambda x: x["id"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    meta = {
        "engine": "pagesift",
        "set": "wcxb_test511",
        "concurrency": concurrency,
        "total": len(items),
        "successful": ok_count,
        "wall_s": round(elapsed, 3),
        "qps": round(qps, 2)
    }
    write_json(out_jsonl.with_suffix(".meta.json"), meta)
    print(f"[DONE] Finished {len(items)} pages in {elapsed:.2f}s ({qps:.1f} pages/s, {ok_count}/{len(items)} OK). Saved to {out_jsonl}")


if __name__ == "__main__":
    c = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    run_test_split(concurrency=c)
