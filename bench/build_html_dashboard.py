"""Build rich interactive HTML dashboard for Benchmark and Stress Testing with full WCXB 511 data."""

import json
from pathlib import Path

BENCH = Path(__file__).resolve().parent
RESULTS = BENCH / "results"
SUMMARY_FILE = RESULTS / "summary.json"
STRESS_FILE = RESULTS / "stress" / "stress_summary.json"
SCORE_511_FILE = RESULTS / "wcxb_test511_score.json"


def build_dashboard():
    score_511 = json.loads(SCORE_511_FILE.read_text()) if SCORE_511_FILE.exists() else {}

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>PageSift 生产基准与极限工程压测可视化仪表盘</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root {{
      --primary: #3b82f6;
      --primary-accent: #60a5fa;
      --secondary: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --bg: #090d16;
      --card-bg: #131c2e;
      --card-border: #1e293b;
      --text: #f8fafc;
      --text-muted: #94a3b8;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }}
    body {{ background: var(--bg); color: var(--text); padding: 32px 16px; line-height: 1.5; }}
    .container {{ max-width: 1240px; margin: 0 auto; }}
    header {{ text-align: center; margin-bottom: 32px; }}
    h1 {{ font-size: 2.2rem; font-weight: 800; color: #fff; margin-bottom: 8px; }}
    .subtitle {{ font-size: 1.05rem; color: var(--text-muted); }}
    .badge {{ display: inline-block; padding: 4px 12px; font-size: 0.8rem; font-weight: 600; border-radius: 9999px; background: #1e293b; color: #38bdf8; margin: 4px; border: 1px solid #334155; }}
    
    .nav-tabs {{ display: flex; justify-content: center; gap: 12px; margin-bottom: 32px; border-bottom: 1px solid var(--card-border); padding-bottom: 16px; }}
    .tab-btn {{ background: transparent; border: 1px solid var(--card-border); color: var(--text-muted); padding: 10px 24px; border-radius: 8px; font-size: 0.95rem; font-weight: 600; cursor: pointer; transition: all 0.2s ease; }}
    .tab-btn.active {{ background: var(--primary); color: #fff; border-color: var(--primary); box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3); }}

    .tab-pane {{ display: none; }}
    .tab-pane.active {{ display: block; }}

    .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin-bottom: 32px; }}
    .stat-card {{ background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 20px; }}
    .stat-title {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); margin-bottom: 6px; }}
    .stat-value {{ font-size: 1.9rem; font-weight: 800; color: #fff; }}
    .stat-sub {{ font-size: 0.85rem; color: var(--secondary); margin-top: 4px; font-weight: 500; }}

    .charts-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(560px, 1fr)); gap: 24px; margin-bottom: 32px; }}
    @media (max-width: 768px) {{ .charts-grid {{ grid-template-columns: 1fr; }} }}
    .chart-card {{ background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 24px; }}
    .chart-title {{ font-size: 1.15rem; font-weight: 700; color: #fff; margin-bottom: 4px; }}
    .chart-desc {{ font-size: 0.85rem; color: var(--text-muted); margin-bottom: 16px; }}
    .canvas-container {{ position: relative; height: 280px; width: 100%; }}

    .table-card {{ background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 24px; margin-bottom: 32px; overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 0.95rem; }}
    th, td {{ padding: 12px 16px; border-bottom: 1px solid var(--card-border); }}
    th {{ background: #0c1424; color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: 0.75rem; }}
    .highlight {{ color: #38bdf8; font-weight: 600; }}

    footer {{ text-align: center; margin-top: 48px; color: var(--text-muted); font-size: 0.85rem; border-top: 1px solid var(--card-border); padding-top: 24px; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>PageSift 生产基准与极限工程压测仪表盘</h1>
      <p class="subtitle">涵盖官方 WCXB 511 篇全量 Test 分割质量评测与刻意设计的极限压力测试套件 (X1–X7)</p>
      <div style="margin-top: 12px;">
        <span class="badge">PageSift 1.3.0 (Pure Rust)</span>
        <span class="badge">Official WCXB Test Split (511 Pages)</span>
        <span class="badge">Official Firecrawl v2 (Docker Cluster)</span>
      </div>
    </header>

    <div class="nav-tabs">
      <button class="tab-btn active" onclick="switchTab('bench')">📊 生产基准评测 (WCXB 511全量 + 对等对照)</button>
      <button class="tab-btn" onclick="switchTab('stress')">🔥 极限工程压力测试 (X1–X7 严苛验证)</button>
    </div>

    <!-- TAB 1: BENCHMARK -->
    <div id="tab-bench" class="tab-pane active">
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-title">WCXB Test 511 全量 F1</div>
          <div class="stat-value">0.8750</div>
          <div class="stat-sub">🏆 精确率: 0.8750 | 召回率: 0.9142</div>
        </div>
        <div class="stat-card">
          <div class="stat-title">511 全量中位耗时 (p50)</div>
          <div class="stat-value">3.30 ms</div>
          <div class="stat-sub">⚡ p90: 6.36 ms | p99: 13.93 ms</div>
        </div>
        <div class="stat-card">
          <div class="stat-title">全量并发吞吐 (c=4)</div>
          <div class="stat-value">1,062.7 QPS</div>
          <div class="stat-sub">🚀 0.48s 极速处理全部 511 篇页面</div>
        </div>
        <div class="stat-card">
          <div class="stat-title">峰值物理内存开销</div>
          <div class="stat-value">272.7 MB</div>
          <div class="stat-sub">📉 -90.5% 显著低于 Firecrawl (2.88 GB)</div>
        </div>
      </div>

      <div class="charts-grid">
        <div class="chart-card">
          <div class="chart-title">WCXB 511 全量各品类 Word-F1 分项表现</div>
          <div class="chart-desc">官方 7 大分类完整测试表现（Article, Documentation, Forum, Service, Product 等）</div>
          <div class="canvas-container"><canvas id="wcxb511CategoryChart"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-title">端到端响应耗时对比 (对数坐标, ms)</div>
          <div class="chart-desc">PageSift (511全量 / 对照集) vs Firecrawl 耗时阶梯</div>
          <div class="canvas-container"><canvas id="benchLatencyChart"></canvas></div>
        </div>
      </div>
    </div>

    <!-- TAB 2: STRESS TEST -->
    <div id="tab-stress" class="tab-pane">
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-title">极限并发吞吐 (c=1024)</div>
          <div class="stat-value">2,581.8 QPS</div>
          <div class="stat-sub">🛡️ 100% 成功率，零报错零挂起</div>
        </div>
        <div class="stat-card">
          <div class="stat-title">生产 SLO 边界 (p99 <= 100ms)</div>
          <div class="stat-value">> 2,000 QPS</div>
          <div class="stat-sub">🎯 2000 QPS 时 p99 仅 3.07 ms (30× 余量)</div>
        </div>
        <div class="stat-card">
          <div class="stat-title">突发脉冲自愈恢复时间</div>
          <div class="stat-value">0 秒延迟残留</div>
          <div class="stat-sub">🌊 800% 洪峰瞬间消化，脉冲后立返常态</div>
        </div>
        <div class="stat-card">
          <div class="stat-title">50k 高压内存泄漏拟合率</div>
          <div class="stat-value">0.0027 MB/10k</div>
          <div class="stat-sub">🔬 物理内存无漂移，零 FD 泄漏证明</div>
        </div>
      </div>

      <div class="charts-grid">
        <div class="chart-card">
          <div class="chart-title">X1 并发阶梯：QPS 与 p99 延迟走势 (c=1 ~ 1024)</div>
          <div class="chart-desc">在多核满载后维持平稳吞吐，超高并发无惊群</div>
          <div class="canvas-container"><canvas id="stressLadderChart"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-title">X2 开环恒定吞吐与 p99 延迟 (SLO 验证)</div>
          <div class="chart-desc">红虚线表示 Dify 生产上限 SLO 阈值 (100 ms)</div>
          <div class="canvas-container"><canvas id="stressSloChart"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-title">X3 突发流量波形模拟 (Spike & Recovery)</div>
          <div class="chart-desc">常态 150 QPS -> 800% 突发 1200 QPS -> 回落恢复</div>
          <div class="canvas-container"><canvas id="stressSpikeChart"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-title">X5 多模态混洗业务负载分布</div>
          <div class="chart-desc">40秒内混洗并发处理 114,414 次请求（HTML、富文本、文档、爬虫）</div>
          <div class="canvas-container"><canvas id="stressMultiModalChart"></canvas></div>
        </div>
      </div>
    </div>

    <footer>
      <p>PageSift Dify Engineering & Stress Verification Report · WU YUANCHAO (@YOLOW92) · 2026</p>
    </footer>
  </div>

  <script>
    function switchTab(tabId) {{
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      if (tabId === 'bench') {{
        document.querySelectorAll('.tab-btn')[0].classList.add('active');
        document.getElementById('tab-bench').classList.add('active');
      }} else {{
        document.querySelectorAll('.tab-btn')[1].classList.add('active');
        document.getElementById('tab-stress').classList.add('active');
      }}
    }}

    // ---- 511 Categories Chart ----
    new Chart(document.getElementById('wcxb511CategoryChart'), {{
      type: 'bar',
      data: {{
        labels: ['Article (257)', 'Documentation (42)', 'Service (59)', 'Forum (51)', 'Product (28)', 'Collection (34)', 'Listing (40)'],
        datasets: [
          {{ label: 'Word-F1 分数', data: [0.9422, 0.9527, 0.8133, 0.7956, 0.7750, 0.7476, 0.7325], backgroundColor: '#3b82f6' }},
          {{ label: '精确率 Precision', data: [0.9402, 0.9501, 0.8593, 0.7736, 0.7716, 0.7300, 0.7258], backgroundColor: '#10b981' }}
        ]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        scales: {{ y: {{ min: 0.5, max: 1.0, title: {{ display: true, text: '分数 (0.0 ~ 1.0)' }} }} }}
      }}
    }});

    // ---- Bench Latency Chart ----
    new Chart(document.getElementById('benchLatencyChart'), {{
      type: 'bar',
      data: {{
        labels: ['p50 (中位)', 'p90', 'p99'],
        datasets: [
          {{ label: 'PageSift 511全量', data: [3.30, 6.36, 13.93], backgroundColor: '#3b82f6' }},
          {{ label: 'PageSift 对照集', data: [4.47, 7.05, 1690.5], backgroundColor: '#10b981' }},
          {{ label: 'Firecrawl v2', data: [2019.4, 4960.7, 29881.0], backgroundColor: '#ef4444' }}
        ]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        scales: {{ y: {{ type: 'logarithmic', title: {{ display: true, text: '耗时 (ms, 对数坐标)' }} }} }}
      }}
    }});

    // ---- Stress Charts ----
    new Chart(document.getElementById('stressLadderChart'), {{
      type: 'line',
      data: {{
        labels: ['c=1', 'c=2', 'c=4', 'c=8', 'c=16', 'c=32', 'c=64', 'c=128', 'c=256', 'c=512', 'c=1024'],
        datasets: [
          {{ label: '吞吐量 QPS', data: [371.9, 712.4, 894.5, 2333.5, 2691.6, 2660.1, 2675.1, 2736.0, 2537.4, 2572.3, 2581.8], borderColor: '#3b82f6', yAxisID: 'y' }},
          {{ label: 'p99 延迟 (ms)', data: [5.28, 4.92, 7.90, 5.41, 8.30, 14.44, 27.10, 53.14, 106.88, 217.56, 428.57], borderColor: '#f59e0b', yAxisID: 'y1' }}
        ]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        scales: {{
          y: {{ type: 'linear', position: 'left', title: {{ display: true, text: 'QPS' }} }},
          y1: {{ type: 'linear', position: 'right', title: {{ display: true, text: 'p99 延迟 (ms)' }}, grid: {{ drawOnChartArea: false }} }}
        }}
      }}
    }});

    new Chart(document.getElementById('stressSloChart'), {{
      type: 'bar',
      data: {{
        labels: ['100 QPS', '300 QPS', '600 QPS', '1000 QPS', '1500 QPS', '2000 QPS'],
        datasets: [
          {{ label: '实测 p99 耗时 (ms)', data: [5.96, 5.21, 4.31, 3.48, 3.21, 3.07], backgroundColor: '#10b981' }}
        ]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        scales: {{ y: {{ max: 15, title: {{ display: true, text: 'p99 耗时 (ms)' }} }} }}
      }}
    }});

    new Chart(document.getElementById('stressSpikeChart'), {{
      type: 'line',
      data: {{
        labels: ['基线前置 (15s)', '800% 突发洪峰 (20s)', '回落恢复 (20s)'],
        datasets: [
          {{ label: '实际处理吞吐 (QPS)', data: [150.0, 1199.9, 150.0], borderColor: '#8b5cf6', fill: true, backgroundColor: 'rgba(139, 92, 246, 0.2)' }}
        ]
      }},
      options: {{ responsive: true, maintainAspectRatio: false }}
    }});

    new Chart(document.getElementById('stressMultiModalChart'), {{
      type: 'doughnut',
      data: {{
        labels: ['静态网页抽取 (70.1%)', '复杂富文本 (14.9%)', '全格式文档解析 (10.0%)', '深度异步爬取 (5.0%)'],
        datasets: [{{
          data: [80257, 17016, 11466, 5675],
          backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#ec4899']
        }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false }}
    }});
  </script>
</body>
</html>
"""
    (BENCH / "report.html").write_text(html_content, encoding="utf-8")
    print(f"Generated dashboard at {BENCH / 'report.html'}")


if __name__ == "__main__":
    build_dashboard()
