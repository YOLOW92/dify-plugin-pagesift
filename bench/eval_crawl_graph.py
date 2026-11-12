"""Evaluate synthetic site graph traversal, loop detection, and deduplication for PageSift Crawl."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import post_json, write_json

BENCH_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = BENCH_DIR / "corpus" / "crawl_fixture"
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = BENCH_DIR / "results" / "crawl_evaluation.json"

PAGESIFT_BASE = "http://127.0.0.1:3002"
CORPUS_BASE = "http://127.0.0.1:8800"


def generate_synthetic_site():
    (FIXTURES_DIR / "index.html").write_text("""<!DOCTYPE html><html><body>
<h1>Home</h1>
<a href="page1.html">Page 1</a>
<a href="page2.html">Page 2</a>
<a href="loop.html">Loop Page</a>
</body></html>""", encoding="utf-8")

    (FIXTURES_DIR / "page1.html").write_text("""<!DOCTYPE html><html><body>
<h1>Page 1</h1>
<p>Content of page 1.</p>
<a href="index.html">Back Home</a>
</body></html>""", encoding="utf-8")

    (FIXTURES_DIR / "page2.html").write_text("""<!DOCTYPE html><html><body>
<h1>Page 2</h1>
<p>Content of page 2.</p>
<a href="page3.html">Deep Page 3</a>
</body></html>""", encoding="utf-8")

    (FIXTURES_DIR / "page3.html").write_text("""<!DOCTYPE html><html><body>
<h1>Page 3</h1>
<p>Deep terminal content.</p>
</body></html>""", encoding="utf-8")

    (FIXTURES_DIR / "loop.html").write_text("""<!DOCTYPE html><html><body>
<h1>Loop Node</h1>
<a href="loop.html">Self Cycle</a>
<a href="index.html">Cycle to Root</a>
</body></html>""", encoding="utf-8")
    print(f"Created synthetic graph in {FIXTURES_DIR}")


def test_crawl_job():
    payload = {
        "url": f"{CORPUS_BASE}/crawl_fixture/index.html",
        "limit": 10,
        "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True}
    }

    t0 = time.perf_counter()
    status, body, ms, err = post_json(f"{PAGESIFT_BASE}/v1/crawl", payload, timeout=10.0)
    if status not in (200, 201) or not body:
        return {"ok": False, "error": f"Failed to submit crawl: {err} (HTTP {status})"}

    job_id = body.get("id") or body.get("jobId")

    # Poll job completion via GET
    completed = False
    data = []
    for _ in range(20):
        time.sleep(0.5)
        try:
            req_get = urllib.request.Request(
                f"{PAGESIFT_BASE}/v1/crawl/{job_id}",
                method="GET"
            )
            with urllib.request.urlopen(req_get, timeout=5.0) as resp:
                r_body = json.loads(resp.read().decode("utf-8"))
                st = r_body.get("status")
                if st == "completed":
                    completed = True
                    data = r_body.get("data", [])
                    break
                elif st == "failed":
                    break
        except Exception as e:
            print(f"Poll error: {e}", file=sys.stderr)
            continue

    crawled_urls = [
        p.get("url") or p.get("metadata", {}).get("url") or p.get("metadata", {}).get("sourceURL")
        for p in data
    ]
    res = {
        "ok": completed,
        "job_id": job_id,
        "submitted_limit": 10,
        "pages_retrieved": len(data),
        "deduplicated": len(crawled_urls) == len(set(crawled_urls)),
        "loop_handled": "loop.html" in "".join(crawled_urls),
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "crawled_urls": crawled_urls,
    }
    write_json(OUT_FILE, res)
    print(f"[CRAWL EVAL] Graph crawl completed in {res['elapsed_s']}s (retrieved {res['pages_retrieved']} pages, deduplicated: {res['deduplicated']})")
    return res


if __name__ == "__main__":
    generate_synthetic_site()
    test_crawl_job()
