#!/usr/bin/env python3
"""Execute full WCXB Test Split (511 pages) benchmark evaluation against Firecrawl."""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import read_jsonl, write_json

BENCH_DIR = Path(__file__).resolve().parent
CORPUS_DIR = BENCH_DIR / "corpus"
RESULTS_DIR = BENCH_DIR / "results" / "raw"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

MANIFEST_FILE = CORPUS_DIR / "wcxb_test511.jsonl"
FIRECRAWL_BASE = "http://127.0.0.1:3012"
CORPUS_BASE_FOR_DOCKER = "http://host.docker.internal:8800"


def scrape_firecrawl(item: dict, timeout: float = 25.0) -> dict:
    fid = item["id"]
    target_url = f"{CORPUS_BASE_FOR_DOCKER}/wcxb_test/html/{fid}.html"
    payload = json.dumps({
        "url": target_url,
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
    status = 0
    body = None
    err = None

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            body = json.loads(e.read().decode("utf-8", errors="replace"))
        except Exception:
            err = str(e)
    except Exception as e:
        err = str(e)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    data = (body or {}).get("data") or {}
    markdown = data.get("markdown") or ""
    ok = bool(status == 200 and body and body.get("success") is True and len(markdown) > 0)

    return {
        "id": fid,
        "url": item["url"],
        "local_url": target_url,
        "page_type": item.get("page_type", "article"),
        "ok": ok,
        "http": status,
        "ms": round(elapsed_ms, 3),
        "md_chars": len(markdown),
        "title": (data.get("metadata") or {}).get("title") or "",
        "markdown": markdown,
        "error": err,
    }


def run_firecrawl_511(concurrency: int = 4):
    print(f"\n========================================================")
    print(f" [FIRECRAWL WCXB 511 EVALUATION]")
    print(f" Dataset    : {MANIFEST_FILE.name} (511 pages)")
    print(f" Endpoint   : {FIRECRAWL_BASE}/v1/scrape")
    print(f" Concurrency: {concurrency}")
    print(f"========================================================\n")

    items = read_jsonl(MANIFEST_FILE)
    print(f"[*] Loaded {len(items)} pages from manifest.")

    out_file = RESULTS_DIR / f"firecrawl-wcxb_test511-v2-c{concurrency}.jsonl"
    meta_file = RESULTS_DIR / f"firecrawl-wcxb_test511-v2-c{concurrency}.meta.json"

    t0 = time.perf_counter()
    completed = 0
    success = 0
    records = []

    with open(out_file, "w", encoding="utf-8") as f_out:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            future_to_item = {executor.submit(scrape_firecrawl, item): item for item in items}
            for fut in concurrent.futures.as_completed(future_to_item):
                res = fut.result()
                f_out.write(json.dumps(res, ensure_ascii=False) + "\n")
                f_out.flush()
                records.append(res)
                completed += 1
                if res["ok"]:
                    success += 1
                if completed % 25 == 0 or completed == len(items):
                    elapsed = time.perf_counter() - t0
                    qps = completed / elapsed if elapsed > 0 else 0
                    print(f"  [{completed:3d}/511] Success: {success} | Elapsed: {elapsed:5.1f}s | Speed: {qps:.1f} pages/s")

    total_time = time.perf_counter() - t0
    meta = {
        "engine": "firecrawl",
        "dataset": "wcxb_test511",
        "concurrency": concurrency,
        "total_pages": len(items),
        "success_pages": success,
        "wall_time_sec": round(total_time, 3),
        "qps": round(len(items) / total_time, 2) if total_time > 0 else 0.0,
    }
    write_json(meta_file, meta)

    print(f"\n[DONE] Firecrawl evaluated {len(items)} pages in {total_time:.1f}s ({meta['qps']} pages/s)")
    print(f"Raw results saved to: {out_file.resolve()}\n")


if __name__ == "__main__":
    concurrency = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    run_firecrawl_511(concurrency=concurrency)
