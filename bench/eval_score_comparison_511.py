#!/usr/bin/env python3
"""Score and compare PageSift vs Firecrawl on full WCXB Test Split (511 pages)."""

from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import bootstrap_ci, paired_difference_test, pct, plain, read_jsonl, summary, word_prf, write_json

BENCH_DIR = Path(__file__).resolve().parent
CORPUS_DIR = BENCH_DIR / "corpus"
MANIFEST = CORPUS_DIR / "wcxb_test511.jsonl"
PAGESIFT_RAW = BENCH_DIR / "results" / "raw" / "pagesift-wcxb_test511-v2-c1.jsonl"
FIRECRAWL_RAW = BENCH_DIR / "results" / "raw" / "firecrawl-wcxb_test511-v2-c4.jsonl"
OUT_SCORE = BENCH_DIR / "results" / "wcxb_test511_comparison.json"


def evaluate_511_comparison():
    manifest_rows = read_jsonl(MANIFEST)
    gt_map = {r["id"]: r for r in manifest_rows}

    ps_rows = read_jsonl(PAGESIFT_RAW)
    fc_rows = read_jsonl(FIRECRAWL_RAW)

    ps_map = {r["id"]: r for r in ps_rows}
    fc_map = {r["id"]: r for r in fc_rows}

    all_ids = sorted(gt_map.keys())

    # 1. Independent Evaluation (Cohort A)
    def evaluate_engine(records_map: dict[str, dict]):
        by_type = defaultdict(lambda: {"p": [], "r": [], "f1": []})
        all_p, all_r, all_f1 = [], [], []
        latencies = []
        success_count = 0

        for fid in all_ids:
            gt = gt_map[fid]
            ref = gt.get("ref", "")
            ptype = gt.get("page_type", "article")

            r = records_map.get(fid, {})
            if r.get("ok"):
                success_count += 1
                latencies.append(r.get("ms", 0.0))
                pred = plain(r.get("markdown", ""))
                p, rec, f1 = word_prf(pred, ref)
            else:
                p, rec, f1 = 0.0, 0.0, 0.0

            all_p.append(p)
            all_r.append(rec)
            all_f1.append(f1)
            by_type[ptype]["p"].append(p)
            by_type[ptype]["r"].append(rec)
            by_type[ptype]["f1"].append(f1)

        type_summary = {}
        for pt, vals in sorted(by_type.items()):
            f1_vals = vals["f1"]
            ci_low, ci_high = bootstrap_ci(f1_vals)
            type_summary[pt] = {
                "count": len(f1_vals),
                "precision": round(statistics.fmean(vals["p"]), 4) if vals["p"] else 0.0,
                "recall": round(statistics.fmean(vals["r"]), 4) if vals["r"] else 0.0,
                "f1": round(statistics.fmean(f1_vals), 4) if f1_vals else 0.0,
                "f1_ci95": [ci_low, ci_high],
            }

        return {
            "total_pages": len(all_ids),
            "successful_pages": success_count,
            "success_rate_pct": round(success_count / len(all_ids) * 100.0, 2),
            "precision": round(statistics.fmean(all_p), 4),
            "recall": round(statistics.fmean(all_r), 4),
            "f1": round(statistics.fmean(all_f1), 4),
            "f1_ci95": bootstrap_ci(all_f1),
            "latency_ms": summary(latencies),
            "by_category": type_summary,
        }

    ps_eval = evaluate_engine(ps_map)
    fc_eval = evaluate_engine(fc_map)

    # 2. Common Intersection Set (Cohort B)
    common_ids = [fid for fid in all_ids if ps_map.get(fid, {}).get("ok") and fc_map.get(fid, {}).get("ok")]
    ps_common_f1, fc_common_f1 = [], []
    ps_common_lat, fc_common_lat = [], []

    for fid in common_ids:
        ref = gt_map[fid].get("ref", "")
        ps_pred = plain(ps_map[fid].get("markdown", ""))
        fc_pred = plain(fc_map[fid].get("markdown", ""))

        _, _, ps_f1 = word_prf(ps_pred, ref)
        _, _, fc_f1 = word_prf(fc_pred, ref)

        ps_common_f1.append(ps_f1)
        fc_common_f1.append(fc_f1)
        ps_common_lat.append(ps_map[fid].get("ms", 0.0))
        fc_common_lat.append(fc_map[fid].get("ms", 0.0))

    paired_f1 = paired_difference_test(list(zip(ps_common_f1, fc_common_f1)))
    paired_lat = paired_difference_test(list(zip(ps_common_lat, fc_common_lat)))

    comparison_result = {
        "dataset": "WCXB Test Split (Official Full Split, 511 pages)",
        "pagesift": ps_eval,
        "firecrawl": fc_eval,
        "head_to_head_intersection": {
            "common_count": len(common_ids),
            "pagesift_f1": round(statistics.fmean(ps_common_f1), 4) if ps_common_f1 else 0.0,
            "firecrawl_f1": round(statistics.fmean(fc_common_f1), 4) if fc_common_f1 else 0.0,
            "paired_f1_diff": paired_f1,
            "pagesift_latency_ms": summary(ps_common_lat),
            "firecrawl_latency_ms": summary(fc_common_lat),
            "paired_latency_diff": paired_lat,
        }
    }

    write_json(OUT_SCORE, comparison_result)
    print(f"[EVALUATION COMPLETE] Comparison saved to: {OUT_SCORE.resolve()}")
    return comparison_result


if __name__ == "__main__":
    evaluate_511_comparison()
