#!/usr/bin/env python3
"""Evaluate benchmark results: Quality (WCXB Ground Truth), Latency percentiles, and Resource Usage.

Usage:
    python3 evaluate.py wcxb <pagesift_raw.jsonl> <firecrawl_raw.jsonl>
    python3 evaluate.py summarize [--out results/summary.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import CORPUS, RESULTS, plain, read_jsonl, summary, word_prf, write_json  # noqa: E402


def evaluate_run(raw_jsonl: Path, manifest_path: Path | None = None) -> dict:
    meta_path = raw_jsonl.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    records = read_jsonl(raw_jsonl)

    gt_map = {}
    if manifest_path and manifest_path.exists():
        for row in read_jsonl(manifest_path):
            gt_map[row["id"]] = {
                "ref": row.get("ref", ""),
                "page_type": row.get("page_type", "unknown"),
                "orig_url": row.get("orig_url", "")
            }

    ok_recs = [r for r in records if r.get("ok")]
    latencies = [r["ms"] for r in ok_recs]
    wall_s = meta.get("wall_s") or (sum(latencies) / 1000.0)
    qps = len(ok_recs) / wall_s if wall_s > 0 else 0.0

    # Quality scoring if Ground Truth is present
    quality_by_type = defaultdict(lambda: {"p": [], "r": [], "f1": []})
    all_p, all_r, all_f1 = [], [], []

    for r in ok_recs:
        fid = r["id"]
        if fid in gt_map:
            ref = gt_map[fid]["ref"]
            ptype = gt_map[fid]["page_type"]
            pred = plain(r.get("markdown", ""))
            p, rec, f1 = word_prf(pred, ref)
            all_p.append(p)
            all_r.append(rec)
            all_f1.append(f1)
            quality_by_type[ptype]["p"].append(p)
            quality_by_type[ptype]["r"].append(rec)
            quality_by_type[ptype]["f1"].append(f1)

    type_scores = {}
    for pt, vals in sorted(quality_by_type.items()):
        type_scores[pt] = {
            "count": len(vals["f1"]),
            "precision": round(statistics.fmean(vals["p"]), 4) if vals["p"] else 0.0,
            "recall": round(statistics.fmean(vals["r"]), 4) if vals["r"] else 0.0,
            "f1": round(statistics.fmean(vals["f1"]), 4) if vals["f1"] else 0.0,
        }

    # Monitor memory & CPU if monitor log exists
    run_name = raw_jsonl.stem
    monitor_path = raw_jsonl.parent / f"{run_name}.monitor.jsonl"
    mon_mem, mon_cpu = [], []
    if monitor_path.exists():
        for line in read_jsonl(monitor_path):
            if "mem_mb" in line:
                mon_mem.append(line["mem_mb"])
            if "cpu_pct" in line:
                mon_cpu.append(line["cpu_pct"])

    res = {
        "run_name": run_name,
        "engine": meta.get("engine", run_name.split("-")[0]),
        "set": meta.get("set", ""),
        "concurrency": meta.get("concurrency", 1),
        "total_requests": len(records),
        "successful_requests": len(ok_recs),
        "success_rate": round(len(ok_recs) / len(records) * 100, 2) if records else 0.0,
        "wall_time_s": round(wall_s, 3),
        "qps": round(qps, 2),
        "latency_ms": summary(latencies),
        "quality": {
            "evaluated_pages": len(all_f1),
            "precision": round(statistics.fmean(all_p), 4) if all_p else 0.0,
            "recall": round(statistics.fmean(all_r), 4) if all_r else 0.0,
            "f1": round(statistics.fmean(all_f1), 4) if all_f1 else 0.0,
            "by_type": type_scores,
        },
        "resources": {
            "peak_mem_mb": round(max(mon_mem), 1) if mon_mem else None,
            "avg_mem_mb": round(statistics.fmean(mon_mem), 1) if mon_mem else None,
            "peak_cpu_pct": round(max(mon_cpu), 1) if mon_cpu else None,
            "avg_cpu_pct": round(statistics.fmean(mon_cpu), 1) if mon_cpu else None,
        }
    }
    return res


def print_comparison_table(p_res: dict, f_res: dict):
    print("\n" + "=" * 88)
    print("           HEAD-TO-HEAD BENCHMARK: PageSift vs. Firecrawl (v2 API)")
    print("=" * 88)
    print(f"{'Metric':<35} | {'PageSift':<22} | {'Firecrawl':<22}")
    print("-" * 88)

    # Success rate
    print(f"{'Success Rate':<35} | {p_res['success_rate']}% ({p_res['successful_requests']}/{p_res['total_requests']}){'':<7} | {f_res['success_rate']}% ({f_res['successful_requests']}/{f_res['total_requests']})")
    
    # Latencies
    p_lat = p_res['latency_ms']
    f_lat = f_res['latency_ms']
    print(f"{'Median Latency (p50)':<35} | {p_lat.get('p50', 0):.2f} ms{'':<14} | {f_lat.get('p50', 0):.2f} ms")
    print(f"{'Mean Latency':<35} | {p_lat.get('mean', 0):.2f} ms{'':<14} | {f_lat.get('mean', 0):.2f} ms")
    print(f"{'90th Percentile (p90)':<35} | {p_lat.get('p90', 0):.2f} ms{'':<14} | {f_lat.get('p90', 0):.2f} ms")
    print(f"{'99th Percentile (p99)':<35} | {p_lat.get('p99', 0):.2f} ms{'':<14} | {f_lat.get('p99', 0):.2f} ms")
    print(f"{'Throughput (QPS)':<35} | {p_res['qps']:.2f} pages/s{'':<9} | {f_res['qps']:.2f} pages/s")
    print(f"{'Wall Time (Total)':<35} | {p_res['wall_time_s']:.2f} s{'':<15} | {f_res['wall_time_s']:.2f} s")

    # Quality
    pq, fq = p_res['quality'], f_res['quality']
    if pq.get('evaluated_pages') and fq.get('evaluated_pages'):
        print("-" * 88)
        print(f"{'Extraction Word-F1':<35} | {pq['f1']:.4f}{'':<16} | {fq['f1']:.4f}")
        print(f"{'Extraction Precision':<35} | {pq['precision']:.4f}{'':<16} | {fq['precision']:.4f}")
        print(f"{'Extraction Recall':<35} | {pq['recall']:.4f}{'':<16} | {fq['recall']:.4f}")

    # Memory & CPU
    pr, fr = p_res['resources'], f_res['resources']
    if pr.get('peak_mem_mb') or fr.get('peak_mem_mb'):
        print("-" * 88)
        print(f"{'Peak Memory (RSS / Cluster)':<35} | {pr.get('peak_mem_mb') or 'N/A'} MB{'':<14} | {fr.get('peak_mem_mb') or 'N/A'} MB")
        print(f"{'Average Memory Usage':<35} | {pr.get('avg_mem_mb') or 'N/A'} MB{'':<14} | {fr.get('avg_mem_mb') or 'N/A'} MB")

    print("=" * 88 + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pagesift_raw", type=Path)
    ap.add_argument("firecrawl_raw", type=Path)
    ap.add_argument("--manifest", type=Path, default=CORPUS / "wcxb" / "manifest.jsonl")
    ap.add_argument("--save-summary", type=Path, default=RESULTS / "summary.json")
    args = ap.parse_args()

    p_eval = evaluate_run(args.pagesift_raw, args.manifest)
    f_eval = evaluate_run(args.firecrawl_raw, args.manifest)

    print_comparison_table(p_eval, f_eval)

    summary_data = {
        "pagesift": p_eval,
        "firecrawl": f_eval,
    }
    write_json(args.save_summary, summary_data)
    print(f"[+] Detailed evaluation summary saved to: {args.save_summary}")


if __name__ == "__main__":
    main()
