#!/usr/bin/env python3
"""Send every corpus page to one engine through the Firecrawl v1 `/v1/scrape` API.

    scrape.py <engine> <set> [--concurrency N] [--tag NAME] [--limit N]

engine: pagesift | firecrawl
set:    wcxb (local corpus, needs serve_corpus.py) | live (real URLs from Firecrawl's 1-0-0 dataset)

Both engines get the identical request body:
    {"url": ..., "formats": ["markdown"], "onlyMainContent": true}
Latency is measured on the client, end to end (request sent -> full JSON body received).
Output: results/raw/<engine>-<set>-c<N>[-tag].jsonl, plus a .meta.json with wall time.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import CORPUS, CORPUS_BASE, ENGINES, RESULTS, post_json, read_jsonl, write_json  # noqa: E402


def load_set(name: str, engine: str) -> list[dict]:
    if name == "wcxb":
        rows = read_jsonl(CORPUS / "wcxb" / "manifest.jsonl")
        return [{"id": r["id"], "url": CORPUS_BASE[engine] + r["path"]} for r in rows]
    if name == "wcxb_sample50":
        rows = read_jsonl(CORPUS / "wcxb_sample50.jsonl")
        return [{"id": r["id"], "url": CORPUS_BASE[engine] + r["path"]} for r in rows]
    if name == "live":
        return [{"id": r["id"], "url": r["url"]} for r in read_jsonl(CORPUS / "live.jsonl")]
    if name == "docs":
        return [{"id": r["id"], "url": CORPUS_BASE[engine] + r["path"]} for r in read_jsonl(CORPUS / "docs" / "manifest.jsonl")]
    raise SystemExit(f"unknown set {name}")


def one(engine: str, item: dict, timeout: float, api_version: str = "v2") -> dict:
    payload = {
        "url": item["url"],
        "formats": ["markdown"],
        "onlyMainContent": True,
        "timeout": int(timeout * 1000),
    }
    t_start = time.time()
    endpoint = f"/{api_version}/scrape"
    status, body, ms, err = post_json(ENGINES[engine] + endpoint, payload, timeout=timeout)
    data = (body or {}).get("data") or {}
    ok = bool(status == 200 and body and body.get("success") and data.get("markdown") is not None)
    meta = data.get("metadata") or {}
    return {
        "id": item["id"],
        "url": item["url"],
        "ok": ok,
        "http": status,
        "ms": round(ms, 3),
        "t_start": t_start,
        "error": err or ("" if ok else str((body or {}).get("error", ""))[:300]),
        "source_status": meta.get("statusCode"),
        "markdown": data.get("markdown") or "",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("engine", choices=list(ENGINES))
    ap.add_argument("set", choices=["wcxb", "wcxb_sample50", "live", "docs"])
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--api-version", choices=["v1", "v2"], default="v2")
    ap.add_argument("--tag", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()

    items = load_set(args.set, args.engine)
    if args.limit:
        items = items[: args.limit]
    tag_part = f"-{args.tag}" if args.tag else ""
    name = f"{args.engine}-{args.set}-{args.api_version}-c{args.concurrency}{tag_part}"
    out = RESULTS / "raw" / f"{name}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    done = 0
    with out.open("w") as f, ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for rec in pool.map(lambda it: one(args.engine, it, args.timeout, args.api_version), items):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            done += 1
            if done % 25 == 0 or done == len(items):
                print(f"  {name}: {done}/{len(items)}", flush=True)
    wall = time.time() - t0
    write_json(out.with_suffix(".meta.json"), {
        "engine": args.engine, "set": args.set, "concurrency": args.concurrency,
        "pages": len(items), "wall_s": wall, "t0": t0, "t1": t0 + wall,
    })
    print(f"{name}: {len(items)} pages in {wall:.1f} s -> {out}")


if __name__ == "__main__":
    main()
