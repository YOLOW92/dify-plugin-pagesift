#!/usr/bin/env python3
"""Evaluate benchmark results: Quality (WCXB Ground Truth), Latency percentiles, and Resource Usage.

Supports three reporting cohorts (B02/B03):
- Cohort A: Individual Success Sets (system independent performance)
- Cohort B: Common Intersection Set (strict head-to-head on identical pages)
- Cohort C: Full Set with Failures Scored Zero (resilience & penalty-inclusive evaluation)

Usage:
    python3 evaluate.py wcxb <pagesift_raw.jsonl> <firecrawl_raw.jsonl>
    python3 evaluate.py summarize [--out results/summary.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import (  # noqa: E402
    CORPUS,
    RESULTS,
    paired_difference_test,
    plain,
    read_jsonl,
    summary,
    word_prf,
    write_json,
)


def load_manifest(manifest_path: Path | None) -> dict[str, dict]:
    gt_map = {}
    if manifest_path and manifest_path.exists():
        for row in read_jsonl(manifest_path):
            gt_map[row["id"]] = {
                "ref": row.get("ref", ""),
                "page_type": row.get("page_type", "unknown"),
                "orig_url": row.get("orig_url", ""),
            }
    return gt_map


def evaluate_cohorts(
    ps_records: list[dict],
    fc_records: list[dict],
    gt_map: dict[str, dict]
) -> dict:
    """Evaluate Cohort A (independent), Cohort B (intersection), and Cohort C (full penalty)."""
    ps_by_id = {r["id"]: r for r in ps_records}
    fc_by_id = {r["id"]: r for r in fc_records}

    all_ids = sorted(set(ps_by_id.keys()) | set(fc_by_id.keys()))
    common_ok_ids = sorted([
        fid for fid in all_ids
        if ps_by_id.get(fid, {}).get("ok") and fc_by_id.get(fid, {}).get("ok")
    ])

    def score_records(records: list[dict], target_ids: list[str], penalize_failures: bool = False) -> dict:
        p_list, r_list, f1_list, latencies = [], [], [], []
        by_type = defaultdict(lambda: {"p": [], "r": [], "f1": []})

        for fid in target_ids:
            rec = next((r for r in records if r["id"] == fid), None)
            ref_info = gt_map.get(fid, {})
            ref = ref_info.get("ref", "")
            ptype = ref_info.get("page_type", "unknown")

            if rec and rec.get("ok"):
                latencies.append(rec["ms"])
                pred = plain(rec.get("markdown", ""))
                p, r, f1 = word_prf(pred, ref)
            elif penalize_failures:
                # Cohort C: penalty for failures
                p, r, f1 = 0.0, 0.0, 0.0
                if rec and "ms" in rec:
                    latencies.append(rec["ms"])
            else:
                continue

            p_list.append(p)
            r_list.append(r)
            f1_list.append(f1)
            by_type[ptype]["p"].append(p)
            by_type[ptype]["r"].append(r)
            by_type[ptype]["f1"].append(f1)

        type_scores = {}
        for pt, vals in sorted(by_type.items()):
            type_scores[pt] = {
                "count": len(vals["f1"]),
                "precision": round(statistics.fmean(vals["p"]), 4) if vals["p"] else 0.0,
                "recall": round(statistics.fmean(vals["r"]), 4) if vals["r"] else 0.0,
                "f1": round(statistics.fmean(vals["f1"]), 4) if vals["f1"] else 0.0,
            }

        return {
            "evaluated_pages": len(f1_list),
            "precision": round(statistics.fmean(p_list), 4) if p_list else 0.0,
            "recall": round(statistics.fmean(r_list), 4) if r_list else 0.0,
            "f1": round(statistics.fmean(f1_list), 4) if f1_list else 0.0,
            "latency_ms": summary(latencies),
            "by_type": type_scores,
        }

    # 1. Cohort A: Individual Success Sets
    cohort_a_ps = score_records(ps_records, [r["id"] for r in ps_records if r.get("ok")])
    cohort_a_fc = score_records(fc_records, [r["id"] for r in fc_records if r.get("ok")])

    # 2. Cohort B: Common Intersection Set
    cohort_b_ps = score_records(ps_records, common_ok_ids)
    cohort_b_fc = score_records(fc_records, common_ok_ids)

    # Paired quality and latency difference on common intersection
    f1_pairs = []
    lat_pairs = []
    for fid in common_ok_ids:
        r_ps = ps_by_id[fid]
        r_fc = fc_by_id[fid]
        ref = gt_map.get(fid, {}).get("ref", "")
        f1_ps = word_prf(plain(r_ps.get("markdown", "")), ref)[2]
        f1_fc = word_prf(plain(r_fc.get("markdown", "")), ref)[2]
        f1_pairs.append((f1_ps, f1_fc))
        lat_pairs.append((r_ps["ms"], r_fc["ms"]))

    cohort_b_f1_test = paired_difference_test(f1_pairs)
    cohort_b_lat_test = paired_difference_test(lat_pairs)

    # 3. Cohort C: Full Set with Failures Scored Zero
    cohort_c_ps = score_records(ps_records, all_ids, penalize_failures=True)
    cohort_c_fc = score_records(fc_records, all_ids, penalize_failures=True)

    return {
        "cohort_a_independent": {
            "pagesift": cohort_a_ps,
            "firecrawl": cohort_a_fc,
        },
        "cohort_b_intersection": {
            "common_count": len(common_ok_ids),
            "pagesift": cohort_b_ps,
            "firecrawl": cohort_b_fc,
            "paired_f1_difference": cohort_b_f1_test,
            "paired_latency_difference": cohort_b_lat_test,
        },
        "cohort_c_full_penalty": {
            "total_count": len(all_ids),
            "pagesift": cohort_c_ps,
            "firecrawl": cohort_c_fc,
        }
    }


def evaluate_single_run(raw_jsonl: Path, manifest_path: Path | None = None) -> dict:
    meta_path = raw_jsonl.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    records = read_jsonl(raw_jsonl)
    gt_map = load_manifest(manifest_path)

    ok_recs = [r for r in records if r.get("ok")]
    latencies = [r["ms"] for r in ok_recs]
    wall_s = meta.get("wall_s") or (sum(latencies) / 1000.0)
    qps = len(ok_recs) / wall_s if wall_s > 0 else 0.0

    # Resource usage from monitor
    run_name = raw_jsonl.stem
    monitor_path = raw_jsonl.parent / f"{run_name}.monitor.jsonl"
    mon_mem, mon_cpu = [], []
    if monitor_path.exists():
        for line in read_jsonl(monitor_path):
            if "mem_mb" in line:
                mon_mem.append(line["mem_mb"])
            if "cpu_pct" in line:
                mon_cpu.append(line["cpu_pct"])

    return {
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
        "resources": {
            "peak_mem_mb": round(max(mon_mem), 1) if mon_mem else None,
            "avg_mem_mb": round(statistics.fmean(mon_mem), 1) if mon_mem else None,
            "peak_cpu_pct": round(max(mon_cpu), 1) if mon_cpu else None,
        }
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate benchmark results")
    sub = parser.add_subparsers(dest="cmd")

    p_wcxb = sub.add_parser("wcxb")
    p_wcxb.add_argument("pagesift_raw", type=Path)
    p_wcxb.add_argument("firecrawl_raw", type=Path)
    p_wcxb.add_argument("--manifest", type=Path, default=CORPUS / "wcxb_sample50.jsonl")
    p_wcxb.add_argument("--out", type=Path, default=RESULTS / "wcxb_cohorts.json")

    p_sum = sub.add_parser("summarize")
    p_sum.add_argument("--dir", type=Path, default=RESULTS)
    p_sum.add_argument("--manifest", type=Path, default=CORPUS / "wcxb_sample50.jsonl")
    p_sum.add_argument("--out", type=Path, default=RESULTS / "summary.json")

    args = parser.parse_args()

    if args.cmd == "wcxb":
        gt = load_manifest(args.manifest)
        ps_recs = read_jsonl(args.pagesift_raw)
        fc_recs = read_jsonl(args.firecrawl_raw)
        res = evaluate_cohorts(ps_recs, fc_recs, gt)
        write_json(args.out, res)
        print(f"Wrote cohort evaluation to {args.out}")

    elif args.cmd == "summarize":
        raw_dir = args.dir / "raw" if (args.dir / "raw").exists() else args.dir
        runs = {}
        for p in sorted(raw_dir.glob("*.jsonl")):
            if p.name.endswith(".monitor.jsonl"):
                continue
            evaluated = evaluate_single_run(p, args.manifest)
            runs[evaluated["run_name"]] = evaluated

        # Check for sample50 c=1 runs to compute cohort comparison
        ps_c1 = raw_dir / "pagesift-wcxb_sample50-v2-c1.jsonl"
        fc_c1 = raw_dir / "firecrawl-wcxb_sample50-v2-c1.jsonl"
        cohorts = None
        if ps_c1.exists() and fc_c1.exists():
            gt = load_manifest(args.manifest)
            cohorts = evaluate_cohorts(read_jsonl(ps_c1), read_jsonl(fc_c1), gt)

        out_data = {
            "runs": runs,
            "cohort_comparison": cohorts,
        }
        write_json(args.out, out_data)
        print(f"Wrote summary with cohorts to {args.out}")


if __name__ == "__main__":
    main()
