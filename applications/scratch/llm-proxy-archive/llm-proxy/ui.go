package main

import (
	"net/http"
)

// UI serves a modern WebSocket-based dashboard with tabbed iframes
func (s *Scaler) UI(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write([]byte(uiHTML))
}

const uiHTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>LLM Control Panel</title>
  <style>
    :root {
      --bg-primary: #0d1117;
      --bg-secondary: #161b22;
      --bg-tertiary: #21262d;
      --border-color: #30363d;
      --text-primary: #f0f6fc;
      --text-secondary: #8b949e;
      --accent-blue: #58a6ff;
      --accent-green: #3fb950;
      --accent-red: #f85149;
      --accent-yellow: #d29922;
      --accent-purple: #a371f7;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif;
      background: var(--bg-primary);
      color: var(--text-primary);
      height: 100%;
      overflow: hidden;
    }
    .app-container {
      display: flex;
      flex-direction: column;
      height: 100%;
    }
    .header {
      background: var(--bg-secondary);
      border-bottom: 1px solid var(--border-color);
      padding: 12px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-shrink: 0;
    }
    .header h1 {
      font-size: 18px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .header-center {
      display: flex;
      align-items: center;
      gap: 24px;
    }
    .routing-info {
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 8px 16px;
      background: var(--bg-tertiary);
      border-radius: 8px;
      border: 1px solid var(--border-color);
    }
    .routing-stat {
      display: flex;
      flex-direction: column;
      align-items: center;
      min-width: 60px;
    }
    .routing-stat-value {
      font-size: 16px;
      font-weight: 600;
      color: var(--accent-blue);
    }
    .routing-stat-label {
      font-size: 10px;
      color: var(--text-secondary);
      text-transform: uppercase;
    }
    .routing-divider {
      width: 1px;
      height: 32px;
      background: var(--border-color);
    }
    .routing-toggle {
      display: flex;
      background: var(--bg-primary);
      border-radius: 6px;
      padding: 2px;
      border: 1px solid var(--border-color);
    }
    .routing-toggle button {
      padding: 6px 12px;
      border: none;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.15s;
      background: transparent;
      color: var(--text-secondary);
      flex: unset;
    }
    .routing-toggle button:hover {
      color: var(--text-primary);
    }
    .routing-toggle button.active {
      background: var(--accent-blue);
      color: white;
    }
    .routing-toggle button.active-local {
      background: var(--accent-green);
      color: white;
    }
    .routing-toggle button.active-remote {
      background: var(--accent-yellow);
      color: black;
    }
    .routing-toggle button.active-mac {
      background: var(--accent-purple);
      color: white;
    }
    .routing-toggle button.hidden {
      display: none;
    }
    .active-endpoint {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 6px 12px;
      background: var(--bg-tertiary);
      border-radius: 6px;
      font-size: 12px;
    }
    .active-endpoint-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--accent-green);
      animation: pulse 2s infinite;
    }
    .active-endpoint-dot.remote { background: var(--accent-yellow); }
    .active-endpoint-dot.mac { background: var(--accent-purple); }
    .active-endpoint-dot.none { background: var(--accent-red); animation: none; }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.5; }
    }
    .connection-status {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: var(--text-secondary);
    }
    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--accent-red);
    }
    .status-dot.connected { background: var(--accent-green); }

    /* Loading skeleton */
    .skeleton {
      background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--bg-secondary) 50%, var(--bg-tertiary) 75%);
      background-size: 200% 100%;
      animation: shimmer 1.5s infinite;
      border-radius: 4px;
    }
    @keyframes shimmer {
      0% { background-position: 200% 0; }
      100% { background-position: -200% 0; }
    }
    .skeleton-text {
      height: 14px;
      width: 60px;
      display: inline-block;
    }
    .skeleton-stat {
      height: 28px;
      width: 40px;
    }
    .card.loading .card-body {
      opacity: 0.6;
    }
    .loading-overlay {
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(13, 17, 23, 0.7);
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 12px;
      z-index: 10;
    }
    .spinner {
      width: 32px;
      height: 32px;
      border: 3px solid var(--border-color);
      border-top-color: var(--accent-blue);
      border-radius: 50%;
      animation: spin 1s linear infinite;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }

    /* Tab Navigation */
    .tab-bar {
      background: var(--bg-secondary);
      border-bottom: 1px solid var(--border-color);
      display: flex;
      padding: 0 16px;
      flex-shrink: 0;
      overflow-x: auto;
    }
    .tab {
      padding: 12px 20px;
      cursor: pointer;
      border-bottom: 2px solid transparent;
      color: var(--text-secondary);
      font-size: 13px;
      font-weight: 500;
      display: flex;
      align-items: center;
      gap: 8px;
      white-space: nowrap;
      transition: all 0.15s;
    }
    .tab:hover {
      color: var(--text-primary);
      background: var(--bg-tertiary);
    }
    .tab.active {
      color: var(--accent-blue);
      border-bottom-color: var(--accent-blue);
    }
    .tab-icon {
      font-size: 16px;
    }
    .tab-close {
      margin-left: 4px;
      opacity: 0.5;
      font-size: 14px;
    }
    .tab-close:hover {
      opacity: 1;
    }

    /* Content Area */
    .content-area {
      flex: 1;
      position: relative;
      overflow: hidden;
    }
    .tab-content {
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      display: none;
    }
    .tab-content.active {
      display: block;
    }
    .tab-content iframe {
      width: 100%;
      height: 100%;
      border: none;
    }

    /* Control Panel Content */
    .control-panel {
      height: 100%;
      overflow-y: auto;
      padding: 24px;
    }
    .container {
      max-width: 1400px;
      margin: 0 auto;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
      gap: 20px;
    }
    .card {
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      overflow: hidden;
    }
    .card-header {
      padding: 16px 20px;
      border-bottom: 1px solid var(--border-color);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .card-header h2 {
      font-size: 14px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .card-body { padding: 20px; }
    .badge {
      padding: 4px 10px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 500;
    }
    .badge-running { background: rgba(63, 185, 80, 0.2); color: var(--accent-green); }
    .badge-stopped { background: rgba(248, 81, 73, 0.2); color: var(--accent-red); }
    .badge-starting { background: rgba(210, 153, 34, 0.2); color: var(--accent-yellow); }
    .stat-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 16px;
      margin-bottom: 20px;
    }
    .stat {
      text-align: center;
      padding: 16px;
      background: var(--bg-tertiary);
      border-radius: 8px;
    }
    .stat-value {
      font-size: 28px;
      font-weight: 700;
      color: var(--accent-blue);
    }
    .stat-label {
      font-size: 12px;
      color: var(--text-secondary);
      margin-top: 4px;
    }
    .info-row {
      display: flex;
      justify-content: space-between;
      padding: 12px 0;
      border-bottom: 1px solid var(--border-color);
    }
    .info-row:last-child { border-bottom: none; }
    .info-label { color: var(--text-secondary); font-size: 13px; }
    .info-value { font-size: 13px; font-weight: 500; }
    .controls {
      display: flex;
      gap: 10px;
      margin-top: 16px;
    }
    button {
      flex: 1;
      padding: 10px 16px;
      border: none;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.15s;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
    }
    button:hover { filter: brightness(1.1); }
    button:active { transform: scale(0.98); }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    .btn-primary { background: var(--accent-blue); color: white; }
    .btn-success { background: var(--accent-green); color: white; }
    .btn-danger { background: var(--accent-red); color: white; }
    .btn-warning { background: var(--accent-yellow); color: black; }
    .btn-secondary { background: var(--bg-tertiary); color: var(--text-primary); border: 1px solid var(--border-color); }
    .model-list {
      margin-top: 16px;
      max-height: 200px;
      overflow-y: auto;
    }
    .model-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 12px;
      background: var(--bg-tertiary);
      border-radius: 6px;
      margin-bottom: 8px;
    }
    .model-name { font-weight: 500; font-size: 13px; }
    .model-size { color: var(--text-secondary); font-size: 12px; }
    .progress-bar-container {
      background: var(--bg-tertiary);
      border-radius: 4px;
      height: 8px;
      overflow: hidden;
      margin-top: 16px;
    }
    .progress-bar {
      height: 100%;
      background: linear-gradient(90deg, var(--accent-blue), var(--accent-purple));
      transition: width 0.5s ease;
    }
    .ttl-control {
      display: flex;
      gap: 10px;
      margin-top: 16px;
    }
    .ttl-control select {
      flex: 1;
      padding: 10px 12px;
      background: var(--bg-tertiary);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      color: var(--text-primary);
      font-size: 13px;
    }
    .log-container {
      background: var(--bg-tertiary);
      border-radius: 8px;
      padding: 12px;
      max-height: 200px;
      overflow-y: auto;
      font-family: 'SF Mono', Consolas, monospace;
      font-size: 12px;
    }
    .log-entry {
      padding: 4px 0;
      border-bottom: 1px solid var(--border-color);
    }
    .log-entry:last-child { border-bottom: none; }
    .log-time { color: var(--text-secondary); }
    .log-message { color: var(--text-primary); }
    .ec2-link {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--accent-blue);
      text-decoration: none;
      font-size: 13px;
    }
    .ec2-link:hover { text-decoration: underline; }
    .worker-header {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .worker-icon {
      width: 40px;
      height: 40px;
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 20px;
    }
    .worker-icon.local { background: linear-gradient(135deg, #3fb950, #238636); }
    .worker-icon.remote { background: linear-gradient(135deg, #f0883e, #d29922); }
  </style>
</head>
<body>
  <div class="app-container">
    <div class="header">
      <h1>🤖 Catalyst LLM</h1>
      <div class="header-center">
        <div class="routing-info" id="routing-info">
          <div class="active-endpoint" id="active-endpoint">
            <span class="active-endpoint-dot none" id="active-dot"></span>
            <span id="active-target-text">Loading...</span>
          </div>
          <div class="routing-divider"></div>
          <div class="routing-stat">
            <span class="routing-stat-value" id="local-routed">-</span>
            <span class="routing-stat-label">Local</span>
          </div>
          <div class="routing-stat">
            <span class="routing-stat-value" id="remote-routed">-</span>
            <span class="routing-stat-label">Remote</span>
          </div>
          <div class="routing-stat" id="mac-stat" style="display: none;">
            <span class="routing-stat-value" id="mac-routed">-</span>
            <span class="routing-stat-label">Mac</span>
          </div>
          <div class="routing-divider"></div>
          <div class="routing-toggle" id="routing-toggle">
            <button id="route-auto" onclick="setRouting('auto')">Auto</button>
            <button id="route-local" onclick="setRouting('local')">Local</button>
            <button id="route-remote" onclick="setRouting('remote')">Remote</button>
            <button id="route-mac" class="hidden" onclick="setRouting('mac')">🍎 Mac</button>
          </div>
        </div>
      </div>
      <div class="connection-status">
        <span class="status-dot" id="ws-status"></span>
        <span id="ws-status-text">Connecting...</span>
      </div>
    </div>

    <div class="tab-bar">
      <div class="tab active" data-tab="control" onclick="switchTab('control')">
        <span class="tab-icon">⚙️</span>
        Control Panel
      </div>
      <div class="tab" data-tab="chat" onclick="switchTab('chat')">
        <span class="tab-icon">💬</span>
        Open WebUI
      </div>
      <div class="tab" data-tab="sillytavern" onclick="switchTab('sillytavern')">
        <span class="tab-icon">🎭</span>
        SillyTavern
      </div>
      <div class="tab" data-tab="searxng" onclick="switchTab('searxng')">
        <span class="tab-icon">🔍</span>
        SearXNG
      </div>
      <div class="tab" data-tab="ollama" onclick="switchTab('ollama')">
        <span class="tab-icon">🦙</span>
        Ollama API
      </div>
    </div>

    <div class="content-area">
      <!-- Control Panel Tab -->
      <div class="tab-content active" id="tab-control">
        <div class="control-panel">
          <div class="container">
            <div class="grid">
              <!-- Local Worker Card -->
              <div class="card loading" id="local-card">
                <div class="card-header">
                  <div class="worker-header">
                    <div class="worker-icon local">🏠</div>
                    <div>
                      <h2>Local Ollama</h2>
                      <div style="font-size: 12px; color: var(--text-secondary);">talos06 • Intel Arc 140T</div>
                    </div>
                  </div>
                  <span class="badge badge-stopped" id="local-badge">Loading...</span>
                </div>
                <div class="card-body">
                  <div class="info-row">
                    <span class="info-label">Endpoint</span>
                    <span class="info-value" id="local-url">--</span>
                  </div>
                  <div class="info-row">
                    <span class="info-label">Models Loaded</span>
                    <span class="info-value" id="local-models-count">0</span>
                  </div>
                  <div class="model-list" id="local-models">
                    <div style="color: var(--text-secondary); text-align: center; padding: 20px;">No models loaded</div>
                  </div>
                </div>
              </div>

              <!-- Remote Worker Card -->
              <div class="card loading" id="remote-card">
                <div class="card-header">
                  <div class="worker-header">
                    <div class="worker-icon remote">☁️</div>
                    <div>
                      <h2>EC2 Bigboi</h2>
                      <div style="font-size: 12px; color: var(--text-secondary);" id="ec2-instance-type">r5.2xlarge • us-west-2</div>
                    </div>
                  </div>
                  <div style="display: flex; gap: 8px;">
                    <span class="badge badge-stopped" id="ec2-state-badge" title="EC2 Instance">⚡ Loading...</span>
                    <span class="badge badge-stopped" id="ollama-ready-badge" title="Ollama Service">🦙 Loading...</span>
                  </div>
                </div>
                <div class="card-body">
                  <div class="info-row">
                    <span class="info-label">Endpoint</span>
                    <span class="info-value" id="remote-url">--</span>
                  </div>
                  <div class="info-row">
                    <span class="info-label">Instance ID</span>
                    <span class="info-value" id="ec2-instance-id">--</span>
                  </div>
                  <div class="info-row">
                    <span class="info-label">AWS Console</span>
                    <a class="ec2-link" id="ec2-console-link" href="#" target="_blank">
                      Open Console ↗
                    </a>
                  </div>
                  <div class="model-list" id="remote-models">
                    <div style="color: var(--text-secondary); text-align: center; padding: 20px;">Worker offline</div>
                  </div>
                  <div class="controls">
                    <button class="btn-success" id="btn-start-remote" onclick="sendControl('start', 'remote')">
                      ▶ Start Worker
                    </button>
                    <button class="btn-danger" id="btn-stop-remote" onclick="sendControl('stop', 'remote')">
                      ⏹ Stop Worker
                    </button>
                  </div>
                </div>
              </div>

              <!-- Scaler Control Card -->
              <div class="card loading" id="scaler-card">
                <div class="card-header">
                  <h2>⚙️ Scaler Configuration</h2>
                  <span class="badge" id="scaler-mode-badge">Loading...</span>
                </div>
                <div class="card-body">
                  <div class="stat-grid">
                    <div class="stat">
                      <div class="stat-value" id="stat-requests">0</div>
                      <div class="stat-label">Total Requests</div>
                    </div>
                    <div class="stat">
                      <div class="stat-value" id="stat-cold-starts">0</div>
                      <div class="stat-label">Cold Starts</div>
                    </div>
                    <div class="stat">
                      <div class="stat-value" id="stat-idle">0m</div>
                      <div class="stat-label">Idle Time</div>
                    </div>
                  </div>
                  <div class="info-row">
                    <span class="info-label">Current TTL</span>
                    <span class="info-value" id="current-ttl">15m</span>
                  </div>
                  <div class="info-row">
                    <span class="info-label">Until Shutdown</span>
                    <span class="info-value" id="until-shutdown">--</span>
                  </div>
                  <div class="progress-bar-container">
                    <div class="progress-bar" id="ttl-progress" style="width: 100%"></div>
                  </div>
                  <div class="ttl-control">
                    <select id="ttl-select">
                      <option value="5m">5 minutes</option>
                      <option value="15m" selected>15 minutes</option>
                      <option value="30m">30 minutes</option>
                      <option value="1h">1 hour</option>
                      <option value="2h">2 hours</option>
                      <option value="4h">4 hours</option>
                      <option value="8h">8 hours</option>
                      <option value="24h">24 hours</option>
                    </select>
                    <button class="btn-primary" onclick="sendControl('set_ttl', '', document.getElementById('ttl-select').value)">
                      Set TTL
                    </button>
                  </div>
                  <div class="controls">
                    <button class="btn-warning" id="btn-pause" onclick="sendControl('pause')">
                      ⏸ Pause Auto-Scale
                    </button>
                    <button class="btn-success" id="btn-resume" onclick="sendControl('resume')">
                      ▶ Resume Auto-Scale
                    </button>
                  </div>
                </div>
              </div>

              <!-- Activity Log Card -->
              <div class="card">
                <div class="card-header">
                  <h2>📋 Activity Log</h2>
                  <button class="btn-secondary" onclick="clearLogs()" style="padding: 4px 10px; font-size: 11px;">Clear</button>
                </div>
                <div class="card-body">
                  <div class="log-container" id="log-container">
                    <div class="log-entry">
                      <span class="log-time">[--:--:--]</span>
                      <span class="log-message">Connecting to control panel...</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Open WebUI Tab -->
      <div class="tab-content" id="tab-chat">
        <iframe src="http://chat.talos00" loading="lazy"></iframe>
      </div>

      <!-- SillyTavern Tab -->
      <div class="tab-content" id="tab-sillytavern">
        <iframe src="http://sillytavern.talos00" loading="lazy"></iframe>
      </div>

      <!-- SearXNG Tab -->
      <div class="tab-content" id="tab-searxng">
        <iframe src="http://searxng.talos00" loading="lazy"></iframe>
      </div>

      <!-- Ollama API Tab -->
      <div class="tab-content" id="tab-ollama">
        <iframe src="http://ollama.talos00" loading="lazy"></iframe>
      </div>
    </div>
  </div>

  <script>
    let ws = null;
    let reconnectAttempts = 0;
    const maxReconnectAttempts = 10;
    const logs = [];
    const maxLogs = 50;
    let isLoading = true;
    let currentRoutingMode = 'auto';

    // Update routing info in topbar
    function updateRoutingInfo(scaler) {
      // Update routing stats
      document.getElementById('local-routed').textContent = scaler.local_routed || 0;
      document.getElementById('remote-routed').textContent = scaler.remote_routed || 0;

      // Show/hide Mac stat and button based on whether Mac endpoint is configured
      const hasMac = scaler.has_mac || false;
      document.getElementById('mac-stat').style.display = hasMac ? 'flex' : 'none';
      document.getElementById('route-mac').classList.toggle('hidden', !hasMac);
      if (hasMac) {
        document.getElementById('mac-routed').textContent = scaler.mac_routed || 0;
      }

      // Update active target indicator
      const activeTarget = scaler.active_target || 'none';
      const activeDot = document.getElementById('active-dot');
      const activeText = document.getElementById('active-target-text');

      activeDot.className = 'active-endpoint-dot';
      if (activeTarget === 'local') {
        activeDot.classList.add('local');
        activeText.textContent = '🏠 Local Active';
        activeText.style.color = 'var(--accent-green)';
      } else if (activeTarget === 'remote') {
        activeDot.classList.add('remote');
        activeText.textContent = '☁️ Remote Active';
        activeText.style.color = 'var(--accent-yellow)';
      } else if (activeTarget === 'mac') {
        activeDot.classList.add('mac');
        activeText.textContent = '🍎 Mac Active';
        activeText.style.color = 'var(--accent-purple)';
      } else {
        activeDot.classList.add('none');
        activeText.textContent = '⚠️ No Backend';
        activeText.style.color = 'var(--accent-red)';
      }

      // Update routing mode toggle
      const mode = scaler.routing_mode || 'auto';
      currentRoutingMode = mode;
      updateRoutingToggle(mode);
    }

    function updateRoutingToggle(mode) {
      // Reset all buttons (preserve hidden class for mac button if not configured)
      document.querySelectorAll('.routing-toggle button').forEach(btn => {
        const isHidden = btn.classList.contains('hidden');
        btn.className = isHidden ? 'hidden' : '';
      });

      // Set active button
      const activeBtn = document.getElementById('route-' + mode);
      if (activeBtn) {
        if (mode === 'local') {
          activeBtn.classList.add('active-local');
        } else if (mode === 'remote') {
          activeBtn.classList.add('active-remote');
        } else if (mode === 'mac') {
          activeBtn.classList.add('active-mac');
        } else {
          activeBtn.classList.add('active');
        }
      }
    }

    function setRouting(mode) {
      if (mode === currentRoutingMode) return;
      sendControl('set_routing', '', mode);
      addLog('Switching to ' + mode + ' routing mode');
    }

    // Tab switching
    function switchTab(tabName) {
      // Update tab buttons
      document.querySelectorAll('.tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === tabName);
      });

      // Update content
      document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === 'tab-' + tabName);
      });
    }

    function connect() {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = protocol + '//' + window.location.host + '/_/ws';

      addLog('Connecting to ' + wsUrl + '...');
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        document.getElementById('ws-status').classList.add('connected');
        document.getElementById('ws-status-text').textContent = 'Connected';
        reconnectAttempts = 0;
        addLog('Connected to control panel');
      };

      ws.onclose = () => {
        document.getElementById('ws-status').classList.remove('connected');
        document.getElementById('ws-status-text').textContent = 'Disconnected';
        addLog('Disconnected from control panel');

        if (reconnectAttempts < maxReconnectAttempts) {
          reconnectAttempts++;
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
          addLog('Reconnecting in ' + (delay/1000) + 's...');
          setTimeout(connect, delay);
        }
      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleMessage(data);
      };

      ws.onerror = (error) => {
        addLog('WebSocket error');
        console.error('WebSocket error:', error);
      };
    }

    function handleMessage(data) {
      switch (data.type) {
        case 'status':
          updateStatus(data);
          break;
        case 'response':
          addLog(data.message || data.status);
          break;
        case 'log':
          addLog(data.message, data.level);
          break;
      }
    }

    function updateStatus(data) {
      // Remove initial loading state
      isLoading = false;
      document.querySelectorAll('.card.loading').forEach(c => c.classList.remove('loading'));

      // Update scaler stats
      if (data.scaler) {
        document.getElementById('stat-requests').textContent = data.scaler.requests_total || 0;
        document.getElementById('stat-cold-starts').textContent = data.scaler.cold_starts || 0;
        document.getElementById('stat-idle').textContent = formatDuration(data.scaler.idle);
        document.getElementById('current-ttl').textContent = data.scaler.idle_timeout;
        document.getElementById('until-shutdown').textContent = data.scaler.until_shutdown;

        // Update progress bar
        const idleSec = parseDuration(data.scaler.idle);
        const timeoutSec = parseDuration(data.scaler.idle_timeout);
        const pct = Math.max(0, Math.min(100, ((timeoutSec - idleSec) / timeoutSec) * 100));
        document.getElementById('ttl-progress').style.width = pct + '%';

        // Update pause/resume buttons
        const paused = data.scaler.paused;
        document.getElementById('btn-pause').disabled = paused;
        document.getElementById('btn-resume').disabled = !paused;

        const modeBadge = document.getElementById('scaler-mode-badge');
        modeBadge.textContent = paused ? 'Paused' : 'Active';
        modeBadge.className = 'badge ' + (paused ? 'badge-stopped' : 'badge-running');

        // Update routing info in topbar
        updateRoutingInfo(data.scaler);
      }

      // Update workers
      if (data.workers) {
        data.workers.forEach(worker => {
          if (worker.type === 'local') {
            updateWorkerCard('local', worker);
          } else if (worker.type === 'remote') {
            updateWorkerCard('remote', worker);
          }
        });
      }
    }

    function updateWorkerCard(type, worker) {
      const urlEl = document.getElementById(type + '-url');
      const modelsEl = document.getElementById(type + '-models');
      const modelsCountEl = document.getElementById(type + '-models-count');

      // Update URL
      urlEl.textContent = worker.url || '--';

      // Update models
      if (worker.models && worker.models.length > 0) {
        if (modelsCountEl) modelsCountEl.textContent = worker.models.length;
        modelsEl.innerHTML = worker.models.map(m =>
          '<div class="model-item">' +
            '<span class="model-name">' + m.name + '</span>' +
            '<span class="model-size">' + m.size + '</span>' +
          '</div>'
        ).join('');
      } else {
        if (modelsCountEl) modelsCountEl.textContent = '0';
        modelsEl.innerHTML = '<div style="color: var(--text-secondary); text-align: center; padding: 20px;">' +
          (worker.ready ? 'No models loaded' : 'Worker offline') + '</div>';
      }

      // Local worker - simple badge
      if (type === 'local') {
        const badge = document.getElementById('local-badge');
        badge.textContent = worker.ready ? 'Online' : 'Offline';
        badge.className = 'badge ' + (worker.ready ? 'badge-running' : 'badge-stopped');
      }

      // EC2-specific updates with dual status
      if (type === 'remote' && worker.ec2) {
        const ec2StateBadge = document.getElementById('ec2-state-badge');
        const ollamaReadyBadge = document.getElementById('ollama-ready-badge');

        // EC2 instance state badge
        const ec2State = worker.ec2.state || 'unknown';
        const ec2Running = ec2State === 'running';
        const ec2Starting = ec2State === 'pending';
        const ec2Stopping = ec2State === 'stopping' || ec2State === 'shutting-down';

        if (ec2Running) {
          ec2StateBadge.textContent = '⚡ Running';
          ec2StateBadge.className = 'badge badge-running';
        } else if (ec2Starting) {
          ec2StateBadge.textContent = '⚡ Starting';
          ec2StateBadge.className = 'badge badge-starting';
        } else if (ec2Stopping) {
          ec2StateBadge.textContent = '⚡ Stopping';
          ec2StateBadge.className = 'badge badge-starting';
        } else {
          ec2StateBadge.textContent = '⚡ Stopped';
          ec2StateBadge.className = 'badge badge-stopped';
        }

        // Ollama ready badge
        const ollamaReady = worker.ec2.ollama_ready;
        ollamaReadyBadge.textContent = ollamaReady ? '🦙 Ready' : '🦙 Offline';
        ollamaReadyBadge.className = 'badge ' + (ollamaReady ? 'badge-running' : 'badge-stopped');

        // Instance info
        document.getElementById('ec2-instance-id').textContent = worker.ec2.instance_id || '--';
        document.getElementById('ec2-instance-type').textContent =
          (worker.ec2.instance_type || 'r5.2xlarge') + ' • ' + (worker.ec2.region || 'us-west-2');

        // Console link
        const consoleLink = document.getElementById('ec2-console-link');
        if (worker.ec2.console_url) {
          consoleLink.href = worker.ec2.console_url;
          consoleLink.style.display = 'inline-flex';
        }

        // Update start/stop buttons based on EC2 state
        const canStart = !ec2Running && !ec2Starting;
        const canStop = ec2Running || ec2Starting;
        document.getElementById('btn-start-remote').disabled = !canStart;
        document.getElementById('btn-stop-remote').disabled = !canStop;
      }
    }

    function sendControl(action, target = '', data = '') {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        addLog('Not connected', 'error');
        return;
      }

      const msg = { action, target, data };
      ws.send(JSON.stringify(msg));
      addLog('Sent: ' + action + (target ? ' on ' + target : ''));
    }

    function addLog(message, level = 'info') {
      const now = new Date();
      const time = now.toTimeString().split(' ')[0];

      logs.unshift({ time, message, level });
      if (logs.length > maxLogs) logs.pop();

      const container = document.getElementById('log-container');
      container.innerHTML = logs.map(log =>
        '<div class="log-entry">' +
          '<span class="log-time">[' + log.time + ']</span> ' +
          '<span class="log-message" style="color: ' +
            (log.level === 'error' ? 'var(--accent-red)' : 'var(--text-primary)') + '">' +
            log.message + '</span>' +
        '</div>'
      ).join('');
    }

    function clearLogs() {
      logs.length = 0;
      document.getElementById('log-container').innerHTML = '';
      addLog('Logs cleared');
    }

    function formatDuration(str) {
      if (!str) return '--';
      return str.replace(/(\d+)h/, '$1h ').replace(/(\d+)m/, '$1m ').replace(/(\d+)s/, '$1s').trim();
    }

    function parseDuration(str) {
      if (!str) return 0;
      let seconds = 0;
      const hours = str.match(/(\d+)h/);
      const mins = str.match(/(\d+)m/);
      const secs = str.match(/(\d+)s/);
      if (hours) seconds += parseInt(hours[1]) * 3600;
      if (mins) seconds += parseInt(mins[1]) * 60;
      if (secs) seconds += parseInt(secs[1]);
      return seconds;
    }

    // Initialize
    connect();
  </script>
</body>
</html>
`
