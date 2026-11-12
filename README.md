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

## 📊 Measured Benchmarks vs. Traditional Stacks

*All measurements conducted on standard Linux x86_64 host.*

| Task | PageSift Suite | Next Best Alternative | Speedup | Memory RSS |
| :--- | :--- | :--- | :--- | :--- |
| **HTML to Markdown** | **0.24 ms** | Firecrawl Self-Hosted (~2,000 ms) | **>8,000×** | **25 MB** vs 2,500 MB |
| **Main Content Extraction** | **1.0 ms** | Readability.py (7.26 ms) | **7.26×** | **Zero-Copy Arena** |
| **PDF to Markdown** | **2.4 ms/page** | pypdfium2 (18.6 ms) / pypdf (49.2 ms) | **20.49×** | **0 C/C++ native deps** |
| **Office Documents** | **91.7 files/s** | python-docx / openpyxl (26.9 files/s) | **3.40×** | **Low RAM** |
| **Base64 Transfer** | **20.4 GB/s** | Python `base64` C-ext (2.1 GB/s) | **9.71×** | **AVX2 / NEON SIMD** |

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

---

## 👨‍💻 Author & Contact

* **Developer**: WU YUANCHAO (武远超)
* **GitHub**: [@YOLOW92](https://github.com/YOLOW92)
* **Email**: [wyc610721@gmail.com](mailto:wyc610721@gmail.com)
* **LinkedIn**: [https://www.linkedin.com/in/yolow92/](https://www.linkedin.com/in/yolow92/)
* **Core Repositories**:
  * [PageSift](https://github.com/YOLOW92/pagesift) - The web and document layer for AI agents
  * [yolowhtml](https://github.com/YOLOW92/yolowhtml) - Zero-Copy Arena HTML5 Parser & Markdown Engine
  * [yolowpdf](https://github.com/YOLOW92/yolowpdf) - Zero-Native-Dependency PDF-to-Markdown Library
  * [yolow64](https://github.com/YOLOW92/yolow64) - High-throughput SIMD Base64 codec
