"""Score full WCXB Test Split (511 pages) and output detailed breakdown."""

from collections import defaultdict
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import bootstrap_ci, pct, plain, read_jsonl, summary, word_prf, write_json

BENCH_DIR = Path(__file__).resolve().parent
CORPUS_DIR = BENCH_DIR / "corpus"
MANIFEST = CORPUS_DIR / "wcxb_test511.jsonl"
RAW_FILE = BENCH_DIR / "results" / "raw" / "pagesift-wcxb_test511-v2-c1.jsonl"
OUT_SCORE = BENCH_DIR / "results" / "wcxb_test511_score.json"


def evaluate_test511():
    manifest_rows = read_jsonl(MANIFEST)
    gt_map = {r["id"]: r for r in manifest_rows}

    raw_rows = read_jsonl(RAW_FILE)
    latencies = [r["ms"] for r in raw_rows if r.get("ok")]

    by_type = defaultdict(lambda: {"p": [], "r": [], "f1": []})
    all_p, all_r, all_f1 = [], [], []

    for r in raw_rows:
        fid = r["id"]
        if fid not in gt_map:
            continue
        gt = gt_map[fid]
        ref = gt.get("ref", "")
        ptype = gt.get("page_type", "article")

        if r.get("ok"):
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

    overall_ci = bootstrap_ci(all_f1)
    res = {
        "dataset": "WCXB Test Split (Official v1.0, 511 pages)",
        "total_pages": len(all_f1),
        "successful_pages": sum(1 for r in raw_rows if r.get("ok")),
        "precision": round(statistics.fmean(all_p), 4),
        "recall": round(statistics.fmean(all_r), 4),
        "f1": round(statistics.fmean(all_f1), 4),
        "f1_ci95": overall_ci,
        "latency_ms": summary(latencies),
        "by_category": type_summary,
    }

    write_json(OUT_SCORE, res)
    print(f"\n=== WCXB Test Split (511 pages) Evaluation Completed ===")
    print(f"Overall F1: {res['f1']} (95% CI: {res['f1_ci95']}) | Precision: {res['precision']} | Recall: {res['recall']}")
    print(f"Latency: p50: {res['latency_ms']['p50']} ms | p90: {res['latency_ms']['p90']} ms | p99: {res['latency_ms']['p99']} ms")
    print(f"\n--- Category Breakdown ---")
    for pt, s in type_summary.items():
        print(f"  * {pt:14s} (n={s['count']:3d}): F1 = {s['f1']:.4f} (P: {s['precision']:.4f}, R: {s['recall']:.4f})")


if __name__ == "__main__":
    evaluate_test511()
