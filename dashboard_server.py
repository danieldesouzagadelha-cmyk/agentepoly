"""
Dashboard server for Polymarket Football Bot.
Run alongside bot.py to see live stats in browser.
Usage: python dashboard_server.py
Then open: http://localhost:8765
"""

import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PolyBot — Football Trading Agent</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:ital,wght@0,400;0,700;1,400&family=Syne:wght@400;600;800&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #050a0f;
    --surface: #0b1520;
    --surface2: #112030;
    --border: #1a3045;
    --accent: #00ff9d;
    --accent2: #00b8ff;
    --red: #ff3d5a;
    --yellow: #ffcc00;
    --text: #d0e8ff;
    --muted: #4a7090;
    --mono: 'Space Mono', monospace;
    --sans: 'Syne', sans-serif;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--mono);
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* Grid noise background */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
      linear-gradient(rgba(0,255,157,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,255,157,0.03) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
    z-index: 0;
  }

  .wrap { position: relative; z-index: 1; max-width: 1400px; margin: 0 auto; padding: 24px; }

  /* ── HEADER ── */
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20px 0 32px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 32px;
  }

  .logo {
    display: flex;
    align-items: center;
    gap: 16px;
  }

  .logo-icon {
    width: 48px; height: 48px;
    border-radius: 12px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    display: flex; align-items: center; justify-content: center;
    font-size: 24px;
    box-shadow: 0 0 20px rgba(0,255,157,0.3);
  }

  .logo-text h1 {
    font-family: var(--sans);
    font-size: 22px;
    font-weight: 800;
    color: #fff;
    letter-spacing: -0.5px;
  }

  .logo-text span {
    font-size: 11px;
    color: var(--muted);
    letter-spacing: 2px;
    text-transform: uppercase;
  }

  .status-pill {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    border-radius: 100px;
    font-size: 12px;
    letter-spacing: 1px;
    text-transform: uppercase;
    font-weight: 700;
    border: 1px solid;
  }

  .status-pill.live {
    background: rgba(0,255,157,0.08);
    border-color: var(--accent);
    color: var(--accent);
  }

  .status-pill.sim {
    background: rgba(255,204,0,0.08);
    border-color: var(--yellow);
    color: var(--yellow);
  }

  .dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: currentColor;
    animation: blink 1.2s ease-in-out infinite;
  }

  @keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.2; }
  }

  /* ── STAT CARDS ── */
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
  }

  .stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 20px 24px;
    position: relative;
    overflow: hidden;
    transition: border-color 0.2s;
  }

  .stat-card:hover { border-color: var(--accent2); }

  .stat-card::after {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--accent), transparent);
    opacity: 0.5;
  }

  .stat-label {
    font-size: 10px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 10px;
  }

  .stat-value {
    font-family: var(--sans);
    font-size: 32px;
    font-weight: 800;
    color: #fff;
    line-height: 1;
  }

  .stat-value.positive { color: var(--accent); }
  .stat-value.negative { color: var(--red); }

  .stat-sub {
    font-size: 11px;
    color: var(--muted);
    margin-top: 6px;
  }

  /* ── MAIN GRID ── */
  .main-grid {
    display: grid;
    grid-template-columns: 1fr 380px;
    gap: 24px;
  }

  @media (max-width: 900px) {
    .main-grid { grid-template-columns: 1fr; }
  }

  /* ── SECTION HEADER ── */
  .section-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
  }

  .section-title {
    font-family: var(--sans);
    font-size: 13px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--muted);
  }

  .badge {
    padding: 3px 10px;
    border-radius: 100px;
    font-size: 11px;
    font-weight: 700;
    background: rgba(0,184,255,0.12);
    color: var(--accent2);
    border: 1px solid rgba(0,184,255,0.25);
  }

  /* ── POSITIONS TABLE ── */
  .positions-wrap {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    overflow: hidden;
  }

  .positions-head {
    padding: 20px 24px;
    border-bottom: 1px solid var(--border);
  }

  table {
    width: 100%;
    border-collapse: collapse;
  }

  th {
    font-size: 10px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--muted);
    padding: 12px 16px;
    text-align: left;
    background: rgba(0,0,0,0.2);
    border-bottom: 1px solid var(--border);
  }

  td {
    padding: 14px 16px;
    font-size: 13px;
    border-bottom: 1px solid rgba(26,48,69,0.5);
    vertical-align: middle;
  }

  tr:last-child td { border-bottom: none; }
  tr:hover td { background: rgba(0,255,157,0.03); }

  .outcome-tag {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
  }

  .outcome-home { background: rgba(0,255,157,0.12); color: var(--accent); }
  .outcome-away { background: rgba(0,184,255,0.12); color: var(--accent2); }
  .outcome-draw { background: rgba(255,204,0,0.12); color: var(--yellow); }

  .pnl-pos { color: var(--accent); }
  .pnl-neg { color: var(--red); }

  .match-score {
    font-size: 12px;
    background: var(--surface2);
    padding: 4px 10px;
    border-radius: 8px;
    display: inline-block;
    font-weight: 700;
    letter-spacing: 1px;
  }

  .empty-state {
    padding: 48px 24px;
    text-align: center;
    color: var(--muted);
    font-size: 14px;
  }

  .empty-icon { font-size: 36px; margin-bottom: 12px; }

  /* ── SIDEBAR ── */
  .sidebar { display: flex; flex-direction: column; gap: 24px; }

  .panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    overflow: hidden;
  }

  .panel-head {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    font-family: var(--sans);
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--muted);
  }

  .panel-body { padding: 16px 20px; }

  /* ── LOG ── */
  .log-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-height: 280px;
    overflow-y: auto;
    padding: 16px 20px;
  }

  .log-list::-webkit-scrollbar { width: 4px; }
  .log-list::-webkit-scrollbar-track { background: transparent; }
  .log-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

  .log-item {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 10px;
    align-items: start;
    font-size: 11px;
    line-height: 1.5;
    padding: 8px 10px;
    border-radius: 8px;
    background: var(--surface2);
  }

  .log-time { color: var(--muted); white-space: nowrap; }
  .log-msg.info { color: var(--text); }
  .log-msg.buy { color: var(--accent); }
  .log-msg.sell { color: var(--accent2); }
  .log-msg.warn { color: var(--yellow); }
  .log-msg.error { color: var(--red); }

  /* ── CONFIG PANEL ── */
  .config-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
    font-size: 12px;
  }
  .config-row:last-child { border-bottom: none; }
  .config-key { color: var(--muted); }
  .config-val { color: var(--text); font-weight: 700; }

  /* ── PNL CHART ── */
  .chart-wrap {
    padding: 16px 20px;
    height: 120px;
    position: relative;
  }

  canvas#pnlChart { width: 100% !important; height: 100% !important; }

  /* ── REFRESH INDICATOR ── */
  .refresh-bar {
    height: 2px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
    margin-top: 4px;
  }

  .refresh-progress {
    height: 100%;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    border-radius: 2px;
    animation: progress 10s linear infinite;
    transform-origin: left;
  }

  @keyframes progress {
    0% { width: 0%; }
    100% { width: 100%; }
  }

  /* ── FOOTER ── */
  footer {
    margin-top: 40px;
    padding-top: 20px;
    border-top: 1px solid var(--border);
    font-size: 11px;
    color: var(--muted);
    display: flex;
    justify-content: space-between;
  }
</style>
</head>
<body>
<div class="wrap">

  <header>
    <div class="logo">
      <div class="logo-icon">⚽</div>
      <div class="logo-text">
        <h1>PolyBot</h1>
        <span>Football Trading Agent</span>
      </div>
    </div>
    <div>
      <div id="modePill" class="status-pill sim">
        <span class="dot"></span>
        <span id="modeLabel">Simulation</span>
      </div>
      <div class="refresh-bar"><div class="refresh-progress"></div></div>
    </div>
  </header>

  <!-- STAT CARDS -->
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-label">Balance</div>
      <div class="stat-value" id="balance">—</div>
      <div class="stat-sub">USDC available</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Total PnL</div>
      <div class="stat-value" id="totalPnl">—</div>
      <div class="stat-sub">All time</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Open Positions</div>
      <div class="stat-value" id="openPos">—</div>
      <div class="stat-sub">Active bets</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Win Rate</div>
      <div class="stat-value" id="winRate">—</div>
      <div class="stat-sub" id="winLoss">— wins / — losses</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Closed Bets</div>
      <div class="stat-value" id="closedPos">—</div>
      <div class="stat-sub">Total resolved</div>
    </div>
  </div>

  <!-- MAIN LAYOUT -->
  <div class="main-grid">

    <!-- LEFT: POSITIONS -->
    <div>
      <div class="section-head">
        <span class="section-title">Open Positions</span>
        <span class="badge" id="openBadge">0 active</span>
      </div>
      <div class="positions-wrap">
        <table>
          <thead>
            <tr>
              <th>Match</th>
              <th>Outcome</th>
              <th>Score</th>
              <th>Entry</th>
              <th>Current</th>
              <th>PnL</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody id="positionsBody">
            <tr><td colspan="7"><div class="empty-state"><div class="empty-icon">🔍</div>Scanning for opportunities...</div></td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- RIGHT: SIDEBAR -->
    <div class="sidebar">

      <!-- PNL Chart -->
      <div class="panel">
        <div class="panel-head">PnL History</div>
        <div class="chart-wrap">
          <canvas id="pnlChart"></canvas>
        </div>
      </div>

      <!-- Config -->
      <div class="panel">
        <div class="panel-head">Configuration</div>
        <div class="panel-body" id="configPanel">
          <div class="config-row"><span class="config-key">Max position</span><span class="config-val" id="cfgMaxPos">—</span></div>
          <div class="config-row"><span class="config-key">Stop loss</span><span class="config-val" id="cfgSL">—</span></div>
          <div class="config-row"><span class="config-key">Profit target</span><span class="config-val" id="cfgTP">—</span></div>
          <div class="config-row"><span class="config-key">Sell on goal</span><span class="config-val">✅ Enabled</span></div>
          <div class="config-row"><span class="config-key">Sell minute</span><span class="config-val" id="cfgMin">—</span></div>
          <div class="config-row"><span class="config-key">Max positions</span><span class="config-val" id="cfgMaxP">—</span></div>
        </div>
      </div>

      <!-- Log -->
      <div class="panel">
        <div class="panel-head">Activity Log</div>
        <div class="log-list" id="logList">
          <div class="log-item">
            <span class="log-time">--:--:--</span>
            <span class="log-msg info">Waiting for data...</span>
          </div>
        </div>
      </div>

    </div>
  </div>

  <footer>
    <span>PolyBot v1.0 — Polymarket Football Agent</span>
    <span id="lastUpdate">Last update: never</span>
  </footer>

</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
// ── CHART SETUP ──────────────────────────────
const ctx = document.getElementById('pnlChart').getContext('2d');
const pnlData = { labels: [], data: [] };

const pnlChart = new Chart(ctx, {
  type: 'line',
  data: {
    labels: pnlData.labels,
    datasets: [{
      label: 'PnL (USDC)',
      data: pnlData.data,
      borderColor: '#00ff9d',
      backgroundColor: 'rgba(0,255,157,0.05)',
      borderWidth: 2,
      pointRadius: 3,
      pointBackgroundColor: '#00ff9d',
      tension: 0.4,
      fill: true,
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { display: false },
      y: {
        grid: { color: 'rgba(26,48,69,0.6)' },
        ticks: {
          color: '#4a7090',
          font: { family: 'Space Mono', size: 10 },
          callback: v => `$${v}`
        }
      }
    }
  }
});

// ── DATA FETCH ───────────────────────────────
let pnlHistory = [{ t: new Date().toLocaleTimeString(), v: 0 }];
const log_cache = [];

function fmt(n, prefix='$') {
  const s = Math.abs(n).toFixed(2);
  const sign = n >= 0 ? '+' : '-';
  return `${sign}${prefix}${s}`;
}

function updateUI(data) {
  // Balance
  document.getElementById('balance').textContent = `$${parseFloat(data.balance||0).toFixed(2)}`;

  // PnL
  const pnl = parseFloat(data.stats?.total_pnl_usdc || 0);
  const pnlEl = document.getElementById('totalPnl');
  pnlEl.textContent = fmt(pnl);
  pnlEl.className = 'stat-value ' + (pnl >= 0 ? 'positive' : 'negative');

  // Counts
  document.getElementById('openPos').textContent = data.stats?.open_positions ?? '—';
  document.getElementById('closedPos').textContent = data.stats?.closed_positions ?? '—';
  document.getElementById('openBadge').textContent = `${data.stats?.open_positions ?? 0} active`;

  // Win rate
  const wr = data.stats?.win_rate ?? 0;
  document.getElementById('winRate').textContent = `${(wr*100).toFixed(0)}%`;
  document.getElementById('winLoss').textContent = `${data.stats?.wins ?? 0} wins / ${data.stats?.losses ?? 0} losses`;

  // Config
  if (data.config) {
    document.getElementById('cfgMaxPos').textContent = `$${data.config.max_position_usdc}`;
    document.getElementById('cfgSL').textContent = `-${(data.config.stop_loss_pct*100).toFixed(0)}%`;
    document.getElementById('cfgTP').textContent = `+${(data.config.profit_target_pct*100).toFixed(0)}%`;
    document.getElementById('cfgMin').textContent = `${data.config.sell_after_minutes}'`;
    document.getElementById('cfgMaxP').textContent = data.config.max_open_positions;
  }

  // Mode pill
  const isLive = !data.simulation_mode;
  const pill = document.getElementById('modePill');
  pill.className = 'status-pill ' + (isLive ? 'live' : 'sim');
  document.getElementById('modeLabel').textContent = isLive ? 'Live Trading' : 'Simulation';

  // Positions table
  const tbody = document.getElementById('positionsBody');
  const positions = data.positions || [];
  if (positions.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><div class="empty-icon">⚽</div>No open positions. Bot is scanning...</div></td></tr>`;
  } else {
    tbody.innerHTML = positions.map(p => {
      const pnl = (p.current_price - p.entry_price) / p.entry_price;
      const pnlStr = `${pnl >= 0 ? '+' : ''}${(pnl*100).toFixed(1)}%`;
      const pnlClass = pnl >= 0 ? 'pnl-pos' : 'pnl-neg';
      const outcomeClass = `outcome-${p.outcome}`;
      const score = p.match ? `${p.match.home_score}-${p.match.away_score}` : '—';
      const min = p.match?.minute ? `${p.match.minute}'` : '';
      return `<tr>
        <td>${p.match?.home_team ?? '?'} vs ${p.match?.away_team ?? '?'}</td>
        <td><span class="outcome-tag ${outcomeClass}">${p.outcome}</span></td>
        <td><span class="match-score">${score} ${min}</span></td>
        <td>${parseFloat(p.entry_price).toFixed(4)}</td>
        <td>${parseFloat(p.current_price||p.entry_price).toFixed(4)}</td>
        <td class="${pnlClass}">${pnlStr}</td>
        <td>${p.status}</td>
      </tr>`;
    }).join('');
  }

  // Update PnL chart
  const now = new Date().toLocaleTimeString('en', {hour:'2-digit',minute:'2-digit'});
  if (pnlHistory.length === 0 || pnlHistory[pnlHistory.length-1].t !== now) {
    pnlHistory.push({ t: now, v: pnl });
    if (pnlHistory.length > 30) pnlHistory.shift();
    pnlChart.data.labels = pnlHistory.map(p => p.t);
    pnlChart.data.datasets[0].data = pnlHistory.map(p => p.v);
    pnlChart.data.datasets[0].borderColor = pnl >= 0 ? '#00ff9d' : '#ff3d5a';
    pnlChart.update('none');
  }

  // Logs
  if (data.logs?.length) {
    const logList = document.getElementById('logList');
    logList.innerHTML = data.logs.slice(-20).reverse().map(l => {
      const type = l.includes('BUY') ? 'buy' : l.includes('SELL') ? 'sell' : l.includes('ERROR') ? 'error' : l.includes('WARNING') ? 'warn' : 'info';
      const parts = l.split(' ', 2);
      const time = parts[0] || '';
      const msg = l.slice(time.length).trim();
      return `<div class="log-item"><span class="log-time">${time}</span><span class="log-msg ${type}">${msg}</span></div>`;
    }).join('');
  }

  document.getElementById('lastUpdate').textContent = `Last update: ${new Date().toLocaleTimeString()}`;
}

// ── POLL API ─────────────────────────────────
async function fetchData() {
  try {
    const resp = await fetch('/api/status');
    if (!resp.ok) return;
    const data = await resp.json();
    updateUI(data);
  } catch (e) {
    // Server not running yet
    console.log('Bot server not reachable, showing demo data');
    updateUI(getDemoData());
  }
}

function getDemoData() {
  const t = Date.now();
  return {
    simulation_mode: true,
    balance: 487.50,
    stats: { open_positions: 2, closed_positions: 7, total_pnl_usdc: 12.40, win_rate: 0.71, wins: 5, losses: 2 },
    config: { max_position_usdc: 50, stop_loss_pct: 0.40, profit_target_pct: 0.30, sell_after_minutes: 70, max_open_positions: 5 },
    positions: [
      { match: { home_team: 'Arsenal', away_team: 'Chelsea', home_score: 1, away_score: 0, minute: 38 }, outcome: 'home', entry_price: 0.4820, current_price: 0.6340, status: 'open' },
      { match: { home_team: 'Barcelona', away_team: 'Atletico', home_score: 0, away_score: 0, minute: 12 }, outcome: 'home', entry_price: 0.5100, current_price: 0.4980, status: 'open' },
    ],
    logs: [
      `${new Date().toLocaleTimeString()} [INFO] BUY Arsenal home @ 0.4820 | $25.00 USDC`,
      `${new Date(t-60000).toLocaleTimeString()} [INFO] Goal detected: Arsenal 1-0 Chelsea [38']`,
      `${new Date(t-120000).toLocaleTimeString()} [INFO] Scanning for pre-game opportunities...`,
      `${new Date(t-180000).toLocaleTimeString()} [INFO] BUY Barcelona home @ 0.5100 | $25.00 USDC`,
      `${new Date(t-240000).toLocaleTimeString()} [INFO] SELL Real Madrid home @ 0.7120 | +$18.20 PnL`,
      `${new Date(t-300000).toLocaleTimeString()} [INFO] Bot started in SIMULATION mode`,
    ]
  };
}

fetchData();
setInterval(fetchData, 10000);
</script>
</body>
</html>"""

class BotAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass  # Silence HTTP logs

    def do_GET(self):
        if self.path == '/api/status':
            self.send_status()
        else:
            self.send_dashboard()

    def send_dashboard(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(DASHBOARD_HTML.encode())

    def send_status(self):
        """Read bot state and return as JSON"""
        data = {
            "simulation_mode": True,
            "balance": 500.0,
            "stats": {"open_positions": 0, "closed_positions": 0, "total_pnl_usdc": 0, "win_rate": 0, "wins": 0, "losses": 0},
            "positions": [],
            "logs": [],
            "config": {
                "max_position_usdc": 50,
                "stop_loss_pct": 0.40,
                "profit_target_pct": 0.30,
                "sell_after_minutes": 70,
                "max_open_positions": 5
            }
        }

        # Try to read portfolio state
        try:
            if os.path.exists("portfolio_state.json"):
                with open("portfolio_state.json") as f:
                    state = json.load(f)
                data["stats"]["total_pnl_usdc"] = state.get("total_pnl", 0)
        except: pass

        # Try to read logs
        try:
            if os.path.exists("bot.log"):
                with open("bot.log") as f:
                    lines = f.readlines()
                data["logs"] = [l.strip() for l in lines[-50:]]
        except: pass

        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)


def run_dashboard(port=8765):
    server = HTTPServer(('0.0.0.0', port), BotAPIHandler)
    print(f"📊 Dashboard running at http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_dashboard()
