#!/usr/bin/env bash
# ==============================================================================
# One-Click Benchmark Runner & Visualization for PageSift vs. Firecrawl (v2 API)
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR/bench"

echo "=========================================================="
echo " Running PageSift vs. Firecrawl Automated Benchmark Suite "
echo "=========================================================="

python3 run_suite.py

echo ""
echo "=========================================================="
echo " Benchmark & Evaluation Finished!"
echo " Markdown Report : $DIR/bench/BENCHMARK_REPORT.md"
echo " HTML Dashboard  : $DIR/bench/report.html"
echo "=========================================================="
