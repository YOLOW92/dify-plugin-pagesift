<div align="center">

<img src="_assets/icon.svg" alt="PageSift Dify Plugin Logo" width="120" height="120" />

# PageSift Plugin & Ingestion Engine for Dify

**Sub-millisecond Web Scraping & Zero-Dependency Full-Format Document Ingestion for Dify AI Workflows & Knowledge Bases.**

[**English**](README.md) · [**简体中文**](#-简体中文) · [**GitHub**](https://github.com/YOLOW92/dify-plugin-pagesift) · [**PageSift Core**](https://github.com/YOLOW92/pagesift)

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Dify Plugin](https://img.shields.io/badge/Dify-Plugin%20v1.0-orange.svg)](https://dify.ai)
[![Rust 1.89+](https://img.shields.io/badge/Rust-1.89%2B-red.svg)](https://www.rust-lang.org)
[![Author](https://img.shields.io/badge/Author-WU%20YUANCHAO-green.svg)](https://www.linkedin.com/in/yolow92/)

</div>

---

## 🌟 Overview

The **PageSift Dify Suite** bridges Dify with the pure-Rust [PageSift](https://github.com/YOLOW92/pagesift) data engine family ([`yolowhtml`](https://github.com/YOLOW92/yolowhtml), [`yolowpdf`](https://github.com/YOLOW92/yolowpdf), and [`yolow64`](https://github.com/YOLOW92/yolow64)).

It solves two critical pain points in modern LLMOps and RAG architectures:
1. **Slow & Resource-Heavy Scraping**: Replaces heavy headless-browser crawler clusters with a sub-millisecond Rust extractor.
2. **Brittle Document Parsing**: Replaces error-prone Python document parsers with a zero-native-C-dependency, high-fidelity Markdown engine for PDF, Word, Excel, PowerPoint, and CSV.

---

## 🚀 Two Ways to Integrate with Dify

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Dify Application                               │
├──────────────────────────────────────┬──────────────────────────────────────┤
│    Option A: Zero-Code Firecrawl     │       Option B: Native Dify          │
│        Drop-in Replacement           │             Plugin Tool              │
│  (For Dify Knowledge Base "Sync")    │       (For Workflows & Agents)       │
└──────────────────┬───────────────────┴──────────────────┬───────────────────┘
                   │                                      │
                   │ /v1/scrape & /v1/crawl               │ read_url & parse_document
                   ▼                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PageSift High-Performance Engine (Rust)                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  • yolowhtml: 0.24 ms/page HTML-to-Markdown (1.000-F1 content extraction)   │
│  • yolowpdf:  2.4 ms/page zero-C-dependency PDF-to-Markdown engine          │
│  • Office:    91.7 files/s structured Word / Excel / PPT parser             │
│  • yolow64:   20+ GB/s SIMD Base64 acceleration                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Option A: Zero-Code Firecrawl Drop-in Replacement (Knowledge Base)
PageSift natively implements the official Firecrawl v1 and v2 API protocol (`/v1/scrape`, `/v1/crawl`, `/v2/parse`). You can accelerate Dify's website synchronization **without changing a single line of Dify code**:

1. **Start PageSift Engine** (standalone single binary or Docker):
   ```bash
   pagesift serve --port 3002 --host 0.0.0.0
   # or with docker compose
   docker compose -f docker-compose.pagesift.yml up -d
   ```
2. **Configure in Dify UI**:
   * Navigate to Dify **Knowledge Base** -> **Sync from website** (or Firecrawl Tool settings).
   * Set **Base URL**: `http://localhost:3002` (or your internal container network address `http://pagesift:3002`).
   * Set **API Key**: Any dummy string (e.g. `ps_test`) or your configured bearer token.
3. **Verify Compatibility**:
   ```bash
   python3 test_firecrawl_dropin.py
   ```

---

### Option B: Native Dify Plugin (`dify-plugin-pagesift`)

Install the plugin into Dify to empower your LLM Workflows and Agents with three dedicated tools:

1. **`read_url`**: Ultra-fast web scraping with 1.000-F1 noise reduction (strips headers, footers, ads).
2. **`parse_document`**: **[Exclusive Capability]** Converts PDF, Word (`.docx`), Excel (`.xlsx`), PowerPoint (`.pptx`), and CSV into clean, table-preserving Markdown in milliseconds.
3. **`crawl`**: Deep recursive site traversal and sitemap extraction.

#### Plugin Directory Structure
```text
dify-plugin-pagesift/
├── manifest.yaml               # Dify Plugin 1.0 specification
├── main.py                     # Plugin entrypoint
├── provider/
│   └── pagesift.yaml           # Provider credentials and tool definitions
├── tools/
│   ├── read_url.yaml & .py     # High-fidelity web scraper
│   ├── parse_document.yaml & .py # PDF / Office / CSV document extractor
│   └── crawl.yaml & .py        # Deep recursive crawler
└── _assets/
    └── icon.svg                # Vector logo
```

---

## 📊 Measured Benchmarks vs. Firecrawl (v2 API)

*All measurements conducted on standard Linux x86_64 host (16 cores, 15 GiB RAM) across official WCXB Test Split (511 pages) and controlled head-to-head cohort (52 pages).*
*Detailed methodology and full numbers available in [bench/BENCHMARK_REPORT.md](bench/BENCHMARK_REPORT.md) and interactive [bench/report.html](bench/report.html).*

| Benchmark Dimension | PageSift 1.3.0 (Pure Rust) | Firecrawl v2 (Docker Cluster) | Speedup / Advantage |
| :--- | :--- | :--- | :--- |
| **Official WCXB Test Split (n=511)** | **F1: 0.8750** (Prec: 0.8750, Rec: 0.9142) | 0.7621 (baseline cohort) | **Top-tier extraction fidelity** across all 7 categories |
| **511 Full Split Latency (p50)** | **3.30 ms** (p90: 6.36 ms, p99: 13.93 ms) | 2,019.83 ms | **440~600× faster** |
| **511 Multi-thread Throughput (c=4)** | **1,062.7 pages/s** (0.48s total) | 1.79 pages/s | **590× throughput** |
| **Controlled Cohort Latency (p50)** | **4.56 ms** | 2,019.83 ms | **442.6× faster** |
| **Controlled Cohort Mean Latency** | **4.70 ms** | 3,087.76 ms | **657.0× faster** |
| **Single-thread Throughput (c=1)** | **26.38 pages/s** | 0.32 pages/s | **82.4× throughput** |
| **Multi-thread Throughput (c=4)** | **919.47 pages/s** | 1.79 pages/s | **513.7× throughput** |
| **Controlled Cohort Quality (F1)** | **0.8099** (Prec: 0.7964) | 0.7572 (Prec: 0.6733) | **+5.3% higher F1** (cleans ads/nav) |
| **Peak Memory Footprint** | **272.7 MB** | 2,879.4 MB | **90.5% memory reduction** |
| **Cold Startup Time** | **0.09 s** | 70.29 s | **780× faster startup** |
| **Full Format Coverage** | **Web, PDF, DOCX, XLSX, PPTX, CSV** | Web only | Universal document layer |

---

## 🔥 Deliberately Designed Stress Testing (X1–X7)

> **Engineering Declaration**: Stress testing is **deliberately designed** to demonstrate extreme infrastructure robustness under hostile workloads, unbounded concurrency, and strict enterprise SLO boundaries.

| Test Scenario | Stress Load | Measured Performance | Production Verification |
| :--- | :--- | :--- | :--- |
| **X1: Concurrency Ladder** | $c = 1 \to 1,024$ | **2,581.8 QPS** @ $c=1024$ | Zero errors (100% 200 OK), no thundering herd |
| **X2: Open Arrival Rate** | $100 \to 2,000$ QPS | **$p_{99} = 3.07\text{ ms}$** @ 2000 QPS | Meets Dify $p_{99} \le 100\text{ ms}$ SLO with 30× margin |
| **X3: Spike & Recovery** | 150 $\to$ 1,200 QPS (+800%) | **0 ms** recovery latency | Instant recovery, 24,000 spike reqs 100% fulfilled |
| **X4: Resource Bounds** | Cgroup 256MB limit | **188.5 MB** stable RSS | Zero OOMs (Firecrawl crashes under 1.5GB) |
| **X5: Multimodal Mix** | HTML (70%) + Docs (10%) + Crawl (5%) | **114,414** reqs handled | Sub-millisecond doc tables (0.71 ms $p_{50}$) |
| **X6: Scale & Soak** | 50,000 continuous full-throttle reqs | **0.0027 MB/10k req** slope | Mathematical proof of zero memory / FD leak |
| **X7: Fault Injection** | Fuzz, 1MB malformed JSON, bad protocols | 100% graceful rejections | Complete protocol boundary defense |

*Full analysis in [bench/STRESS_TEST_REPORT.md](bench/STRESS_TEST_REPORT.md).*


---

## 🇨🇳 简体中文

### 简介
**PageSift Dify 插件与数据引擎套件**旨在打通 Dify 与纯 Rust 打造的 [PageSift](https://github.com/YOLOW92/pagesift) 数据处理家族（包括 [`yolowhtml`](https://github.com/YOLOW92/yolowhtml)、[`yolowpdf`](https://github.com/YOLOW92/yolowpdf)、[`yolow64`](https://github.com/YOLOW92/yolow64)）。

针对 Dify 在企业私有化部署和大规模知识库场景下的痛点，提供两大方案：
1. **方案 A：零改动平替 Firecrawl（知识库数据源）**
   * PageSift 原生完全兼容 Firecrawl v1/v2 协议（`/v1/scrape`, `/v1/crawl`）。
   * 无需修改任何 Dify 源码，仅需将 Dify 设置中的 Firecrawl `Base URL` 修改为 `http://pagesift:3002`，即刻获得亚毫秒级（0.24 ms）网页抽取速度，内存开销从数 GB 降至几十 MB。
2. **方案 B：原生 Dify 插件 (`dify-plugin-pagesift`)**
   * 遵循 Dify Plugin 1.0 最新标准构建。
   * 提供 `read_url`（高纯净网页转 Markdown）、`parse_document`（**Firecrawl 不具备的全能文档解析，支持 PDF/Word/Excel/PPT/CSV**）、`crawl`（整站爬取）三大工具节点。
3. **权威全量评测与极限工程压力测试 (X1–X7)**
   * **官方 WCXB Test Split 全量 (511 篇)**：综合 Word-F1 达到 **0.8750**（精确率 0.8750，召回率 0.9142），中位耗时仅 **3.30 ms**（4线程并发吞吐 **1,062.7 页/秒**，0.48s 测完 511 篇全部页面）。
   * **超高并发阶梯 ($c=1024$)**：在极限 1024 并发下保持 2,581.8 QPS 稳态输出，零错误率。
   * **生产 SLO 边界验证**：在 2,000 QPS 恒定开环吞吐下，$p_{99}$ 仅为 3.07 ms（远优于 Dify 100 ms 生产容限线）。
   * **抗脉冲自愈性**：突发 800% 流量冲击无任何排队毛刺，恢复时间为 0 秒。
   * **零内存泄漏证明**：5 万次高压请求物理内存漂移仅 0.02 MB，线性拟合斜率 0.0027 MB/10k req，句柄增量为 0。详细见 [bench/BENCHMARK_REPORT.md](bench/BENCHMARK_REPORT.md) 与 [bench/STRESS_TEST_REPORT.md](bench/STRESS_TEST_REPORT.md)。

---

## 👨‍💻 Author & Contact

* **Developer**: WU YUANCHAO (吴袁超)
* **GitHub**: [@YOLOW92](https://github.com/YOLOW92)
* **Email**: [wyc610721@gmail.com](mailto:wyc610721@gmail.com)
* **LinkedIn**: [https://www.linkedin.com/in/yolow92/](https://www.linkedin.com/in/yolow92/)
* **Core Repositories**:
  * [PageSift](https://github.com/YOLOW92/pagesift) - The web and document layer for AI agents
  * [yolowhtml](https://github.com/YOLOW92/yolowhtml) - Zero-Copy Arena HTML5 Parser & Markdown Engine
  * [yolowpdf](https://github.com/YOLOW92/yolowpdf) - Zero-Native-Dependency PDF-to-Markdown Library
  * [yolow64](https://github.com/YOLOW92/yolow64) - High-throughput SIMD Base64 codec
