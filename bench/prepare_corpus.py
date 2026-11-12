#!/usr/bin/env python3
"""Build the local corpus served to both engines.

    prepare_corpus.py wcxb <wcxb-repo> [--split test]   # decompress WCXB HTML into corpus/wcxb/
    prepare_corpus.py live <firecrawl-1-0-0.csv> [--n 100]  # pick live URLs from Firecrawl's own dataset

WCXB (Web Content Extraction Benchmark) is not redistributed here; clone it from
https://github.com/Murrough-Foley/web-content-extraction-benchmark and pass its path.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import CORPUS, write_json  # noqa: E402


def wcxb(repo: Path, split: str) -> None:
    out = CORPUS / "wcxb"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for f in sorted((repo / split / "html").iterdir()):
        fid = f.name.split(".")[0]
        gt_path = repo / split / "ground-truth" / f"{fid}.json"
        if not gt_path.exists():
            continue
        data = gzip.decompress(f.read_bytes()) if f.name.endswith(".gz") else f.read_bytes()
        (out / f"{fid}.html").write_bytes(data)
        gt = json.loads(gt_path.read_text())
        g = gt.get("ground_truth", gt)
        pt = (gt.get("_internal") or {}).get("page_type") or gt.get("page_type") or "unknown"
        if isinstance(pt, dict):
            pt = pt.get("primary", "unknown")
        if pt == "category":  # same mapping as WCXB's evaluate.py
            pt = "collection"
        rows.append(
            {
                "id": fid,
                "path": f"/wcxb/{fid}.html",
                "orig_url": gt.get("url", ""),
                "page_type": pt,
                "ref": g.get("main_content", ""),
            }
        )
    with (out / "manifest.jsonl").open("w") as m:
        for r in rows:
            m.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wcxb/{split}: {len(rows)} pages -> {out}")


def live(csv_path: Path, n: int) -> None:
    csv.field_size_limit(10**9)
    rows = []
    with csv_path.open(newline="") as f:
        for r in csv.DictReader(f):
            if r["error"] or not r["truth_text"].strip():
                continue
            rows.append({"id": r["id"], "url": r["url"], "truth": r["truth_text"], "lie": r["lie_text"]})
            if len(rows) >= n:
                break
    out = CORPUS / "live.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as m:
        for r in rows:
            m.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"live: {len(rows)} URLs (first {n} error-free rows of {csv_path.name}) -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("wcxb")
    a.add_argument("repo", type=Path)
    a.add_argument("--split", default="test")
    b = sub.add_parser("live")
    b.add_argument("csv", type=Path)
    b.add_argument("--n", type=int, default=100)
    args = ap.parse_args()
    if args.cmd == "wcxb":
        wcxb(args.repo, args.split)
    else:
        live(args.csv, args.n)


if __name__ == "__main__":
    main()
